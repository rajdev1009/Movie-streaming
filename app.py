import os
from flask import Flask, render_template, request, abort
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from dotenv import load_dotenv

# Local development ke liye .env load karega
load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION ---
# Secret Key (Session security ke liye)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "default_secret_key")

# MongoDB URI (Database connect karne ke liye)
app.config["MONGO_URI"] = os.getenv("MONGO_URI")

# MongoDB Initialize karna
try:
    mongo = PyMongo(app)
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")

def get_movies_collection():
    return mongo.db.movies

# --- ROUTES (RASTE) ---

@app.route("/")
def index():
    query = request.args.get("q")
    movies_collection = get_movies_collection()
    
    if query:
        # Title search karega (case-insensitive)
        movies_cursor = movies_collection.find(
            {"title": {"$regex": query, "$options": "i"}}
        )
    else:
        # Agar search nahi kiya to recent 20 movies dikhayega
        movies_cursor = movies_collection.find().limit(20)
    
    return render_template("index.html", movies=movies_cursor, search_query=query)

@app.route("/movie/<movie_id>")
def movie_detail(movie_id):
    try:
        oid = ObjectId(movie_id)
    except:
        abort(404)

    movies_collection = get_movies_collection()
    movie = movies_collection.find_one({"_id": oid})

    if not movie:
        abort(404)

    return render_template("movie.html", movie=movie)

# --- ERROR HANDLING ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template("index.html", error="Movie not found."), 404

if __name__ == "__main__":
    app.run(debug=True)
  
