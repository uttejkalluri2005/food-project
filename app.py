from flask import Flask,request,jsonify,render_template,session,redirect,url_for
import mysql.connector
from dotenv import load_dotenv
import os 
import numpy as np
from werkzeug.security import generate_password_hash,check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField,SubmitField,PasswordField,FormField,FieldList
from wtforms.validators import Email,DataRequired,ValidationError,EqualTo
from sklearn.feature_extraction.text import TfidfVectorizer
import joblib
import google.generativeai as genai

load_dotenv("secret.env")

genai.configure(api_key = os.getenv("GOOGLE_API"))

generative_config = {
    "temperature":1,
    "top_p":0.95,
    "top_k":64,
    "max_output_tokens":1000,
}

model = genai.GenerativeModel(
    model_name = "models/gemini-2.5-flash-lite",
    generation_config = generative_config,
)

tf = joblib.load("tfidf.pkl")
nnmod = joblib.load("model.pkl")

app=Flask(__name__)
app.secret_key = os.getenv("secret_key")

class LoginForm(FlaskForm):
    username = StringField('name',validators=[DataRequired()])
    userpassword=PasswordField('pass',validators=[DataRequired()])
    submit = SubmitField("Login")

class RegistrationForm(FlaskForm):
    username=StringField('name',validators=[DataRequired()])
    useremail=StringField('email',validators=[DataRequired(),Email()])
    userpassword = PasswordField('pwd',validators=[DataRequired()])
    confi = PasswordField('confirmation',validators=[DataRequired(),EqualTo("userpassword")])
    submit = SubmitField("Register")




con=mysql.connector.connect(
    host= "localhost",
    user= "root",
    password=os.getenv("sql_pass"),
    database="foods"
)

dishes = mysql.connector.connect(
    host="localhost",
    user="root",
    password = os.getenv("sql_pass"),
    database="foods",
    buffered=True
)

@app.route('/')
def home_page():
    return render_template("index.html")

@app.route('/login',methods=["POST","GET"])
def login():
    form =LoginForm()
    if form.validate_on_submit():
        name = form.username.data
        pwd = form.userpassword.data
        cursor=con.cursor()
        query="select userid,username,userpassword from user where username=%s"
        cursor.execute(query,(name,))
        result=cursor.fetchone()
        cursor.close()
        if result:
            stored_password = result[2]
            if check_password_hash(stored_password,pwd):
                session["userid"] = result[0]
                session["username"] = result[1]
                return redirect (url_for("dashboard"))
            else:
                return jsonify({"Message":"wrong password"}),401
        else:
            return jsonify({"Message":"username invalid"}),404
    return render_template("login.html",form=form)

@app.route('/register',methods=['POST',"PUT","GET"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        name = form.username.data
        email = form.useremail.data
        pas = form.userpassword.data
        confir = form.confi.data
        cu = con.cursor()
        ce = con.cursor()
        qu = "select username from user where username=%s"
        qe = "select useremail from user where useremail=%s"
        cu.execute(qu,(name,))
        ru = cu.fetchone()
        ce.execute(qe,(email,))
        re = ce.fetchone()
        if ru:
            return jsonify({"Message":"Username already exists"}),409
        if re:
            return jsonify({"Message":"Email already exists"}),409
        cu.close()
        ce.close()

        cursor=con.cursor()
        hashed_pas=generate_password_hash(pas)
        query = "INSERT INTO user (username,useremail,userpassword) values (%s,%s,%s)"
        cursor.execute(query,(name,email,hashed_pas))
        con.commit()
        cursor.close()
        return redirect(url_for("login"))
    return render_template("register.html",form=form)

@app.route("/dashboard",methods=["GET","POST"])
def dashboard():
    if "userid" in session:
        user_id = session["userid"]
        return render_template("dashboard.html")
    else:
        return redirect(url_for("login"))

@app.route("/generate_recipe",methods=["POST","GET"])
def generate_recipe():
    ingredient_names = []
    quantities = []

    for key in request.form.keys():
        if key.startswith("ingredient_name_"):
            ingredient_names.append(request.form[key])
        elif key.startswith("quantity_"):
            quantities.append(request.form[key])

    cleaned_ingredients = " ".join(ingredient_names).lower()
    x_new = tf.transform([cleaned_ingredients])
    dist,indices = nnmod.kneighbors(x_new)
    index = int(indices[0][0]+1)

    session["cleaned_ingredients"] = cleaned_ingredients
    session["quantities"] = quantities

    query = "select dish from newrecipe where dishid=%s"
    foodname = dishes.cursor()
    foodname.execute(query,(index,))
    res = foodname.fetchone()
    foodname.close()
    if res:
        return redirect(url_for("get_dish",dishname=res[0].strip()))
    else:
        return jsonify({"Message":"Not found"}),404

@app.route("/dish/<string:dishname>")
def get_dish(dishname):
    quantities = session.get("quantities",[])

    chat_session = model.start_chat()

    cu = dishes.cursor()
    qi = "select ingredients from newrecipe where dish=%s"
    cu.execute(qi,(dishname,))
    ing = cu.fetchone()
    cu.close()

    prompt = f"""
You are a precise recipe generator. Your sole goal is to provide a clean, structured, and beginner-friendly recipe for **{dishname}**.

**Instructions for Output Formatting:**
1.  **DO NOT** include any introductory or concluding conversational filler sentences.
2.  Start with "Prep Time: [Time]" and "Cook Time: [Time]" on **two separate lines**.
3.  Immediately follow the times with the recipe steps.
4.  **Output the recipe steps EXCLUSIVELY as a Markdown numbered list (1., 2., 3., etc.).**
5.  **CRITICAL:** Ensure there is a **double line break** (two newlines) after every line of text (including the Prep Time and Cook Time lines) and after every single numbered step.
6.  Keep the total steps under 10.
7.  Ensure all ingredients and the right quantities are included in the steps, based on your input: Ingredients: {ing[0]}, Quantities you have: {quantities}.
8.  End the entire output with a single, relevant YouTube video link, using the markdown format: [Watch Video](LINK_HERE).
"""

    response = chat_session.send_message(prompt)
    final = response.text

    reco = tf.transform([ing[0]])
    dist,indices = nnmod.kneighbors(reco)

    recommend_dish=[]
    for i in indices[0][1:]:
        cur = dishes.cursor()
        query = "select dish from newrecipe where dishid=%s"
        cur.execute(query,(int(i+1),))
        row = cur.fetchone()
        recommend_dish.append(row[0])
        cur.close()

    return render_template("recipe.html",**locals())


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__=='__main__':
    app.run(debug=True)
