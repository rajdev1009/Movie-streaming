from app import app, mongo

# App ka context load karte hain taaki database connect ho sake
with app.app_context():
    # 1. Purana data delete karein (safai)
    print("Purana data hata raha hu...")
    mongo.db.movies.delete_many({})

    # 2. Movies ki list
    sample_movies = [
        {
            "title": "Big Buck Bunny",
            "year": 2008,
            "description": "Ek bada khargosh apne doston ke saath jungle mein masti karta hai.",
            "poster": "https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg",
            "youtube_id": "aqz-KE-bpKQ"
        },
        {
            "title": "Sintel",
            "year": 2010,
            "description": "Ek ladki apne khoye hue dragon dost ki talash mein nikalti hai.",
            "poster": "https://upload.wikimedia.org/wikipedia/commons/8/8f/Sintel_poster.jpg",
            "youtube_id": "0Bmhjf0rKe8"
        },
        {
            "title": "Tears of Steel",
            "year": 2012,
            "description": "Future mein robots aur humans ke beech ki ladai ki kahani.",
            "poster": "https://upload.wikimedia.org/wikipedia/commons/f/f1/Tears_of_Steel_poster.jpg",
            "youtube_id": "R6MlUcmOul8"
        },
        {
            "title": "Elephant's Dream",
            "year": 2006,
            "description": "Do ajib log ek ajeeb si machine duniya mein phase hue hain.",
            "poster": "https://upload.wikimedia.org/wikipedia/commons/0/0c/Elephants_Dream_poster.jpg",
            "youtube_id": "TLkA0RELQ1g"
        }
    ]

    # 3. Database mein insert karein
    print("Movies daal raha hu...")
    mongo.db.movies.insert_many(sample_movies)
    print("Ho gaya! 4 Movies add kar di gayi hain.")
  
