import csv
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from flask_migrate import Migrate
from collections import Counter
from flask import render_template
from flask import flash
from flask import Flask, request, jsonify
import requests
from datetime import datetime
from geopy.geocoders import Nominatim
from geopy.distance import distance
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def analyze_sentiment(review):
    analyzer = SentimentIntensityAnalyzer()
    sentiment_score = analyzer.polarity_scores(review)
    if sentiment_score['compound'] >= 0.05:
        return 'Positive'
    elif sentiment_score['compound'] <= -0.05:
        return 'Negative'
    else:
        return 'Neutral'

# Download VADER's resources
nltk.download('vader_lexicon')

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ereview.db'
db = SQLAlchemy(app)
migrate = Migrate(app, db)
# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
class UserVotes(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    review_id = db.Column(db.Integer, db.ForeignKey('review.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)  # 'upvote' or 'downvote'

    # Relationships
    user = db.relationship('User', backref='votes')
    review = db.relationship('Review', backref='user_votes')
# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
# Institution model
class Institution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    reviews = db.relationship('Review', backref='institution', lazy=True)

# Review model
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    institution_id = db.Column(db.Integer, db.ForeignKey('institution.id'), nullable=False)
    user = db.relationship('User', backref='reviews')
    sentiment = db.Column(db.String(20), nullable=True)
    flags = db.Column(db.Integer, default=0)  # New column to store the number of flags
    flagged_as_fake = db.Column(db.Boolean, default=False)  # Whether review is marked as fake
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)
    @property
    def safe_upvotes(self):
        return self.upvotes if self.upvotes is not None else 0

    @property
    def safe_downvotes(self):
        return self.downvotes if self.downvotes is not None else 0
class ReviewFlag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    #review_id = db.Column(db.Integer, db.ForeignKey('review.id'), nullable=False)
    review_id = db.Column(db.Integer, db.ForeignKey('review.id', ondelete='CASCADE'), nullable=False)
    user = db.relationship('User', backref='flags')
    review = db.relationship('Review', backref='review_flags')

# Load user for login management
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            login_user(user)
            return redirect(url_for('institutions'))
        else:
            return 'Invalid credentials'
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/search_colleges', methods=['GET'])
@login_required
def search_colleges():
    query = request.args.get('query')
    if query:
        search_results = Institution.query.filter(Institution.name.ilike(f'%{query}%')).all()
        return render_template('institutions.html', institutions=search_results)
    return redirect(url_for('institutions'))

@app.route('/institutions')
@login_required
def institutions():
    institutions = Institution.query.all()
    return render_template('institutions.html', institutions=institutions)
@app.route('/trending_reviews')
def trending_reviews():
    # Fetch trending reviews based on upvotes
    trending_reviews = (
        db.session.query(Review, Institution.name.label("institution_name"))
        .join(Institution, Review.institution_id == Institution.id)
        .order_by(Review.upvotes.desc())
        .limit(5)
        .all()
    )
    return render_template('trending_reviews.html', trending_reviews=trending_reviews)
@app.route('/institution/<int:id>')
@login_required
def institution(id):
    institution = Institution.query.get_or_404(id)
    reviews = Review.query.filter_by(institution_id=id).all()
    institutions_list = Institution.query.all()
    for review in reviews:
        user_vote = UserVotes.query.filter_by(user_id=current_user.id, review_id=review.id).first()
        review.user_has_upvoted = user_vote and user_vote.vote_type == 'upvote'
        review.user_has_downvoted = user_vote and user_vote.vote_type == 'downvote'
        review.upvotes = review.upvotes if review.upvotes is not None else 0
        review.downvotes = review.downvotes if review.downvotes is not None else 0
    for review in reviews:
        print(f"Review ID: {review.id}, Content: {review.content}")
    # Sentiment analysis summary
    sentiment_counts = Counter([review.sentiment for review in reviews])
    total_reviews = len(reviews)
    if total_reviews > 0:
        sentiment_percentages = {
            'Positive': (sentiment_counts['Positive'] / total_reviews) * 100,
            'Negative': (sentiment_counts['Negative'] / total_reviews) * 100,
            'Neutral': (sentiment_counts['Neutral'] / total_reviews) * 100
        }
    else:
        sentiment_percentages = {'Positive': 0, 'Negative': 0, 'Neutral': 0}

    return render_template('institution.html', institution=institution, reviews=reviews, sentiment_percentages=sentiment_percentages)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/load_institutions')
def load_institutions():
    file_path = 'institutions.csv'
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            existing_institution = Institution.query.filter_by(name=row['name']).first()
            if not existing_institution:
                new_institution = Institution(
                    name=row['name'],
                    location=row['location'],
                    description=row['description']
                )
                db.session.add(new_institution)
        db.session.commit()
    return "Institutions loaded successfully!"

@app.route('/institution/<int:institution_id>/add_review', methods=['GET', 'POST'])
@login_required
def add_review(institution_id):
    institution = Institution.query.get_or_404(institution_id)
    existing_review = Review.query.filter_by(user_id=current_user.id, institution_id=institution_id).first()
    if existing_review:
        return "You have already submitted a review for this institution."
    if request.method == 'POST':
        content = request.form['content']
        new_review = Review(content=content, user_id=current_user.id, institution_id=institution_id)
        db.session.add(new_review)
        db.session.commit()
        return redirect(url_for('institution', id=institution_id))
    return render_template('add_review.html', institution=institution)

@app.route('/submit_review/<int:institution_id>', methods=['POST'])
@login_required
def submit_review(institution_id):
    if request.method == 'POST':
        content = request.form['content']
        sentiment = analyze_sentiment(content)
        new_review = Review(content=content, sentiment=sentiment, user_id=current_user.id, institution_id=institution_id)
        db.session.add(new_review)
        db.session.commit()
        return redirect(url_for('institution', id=institution_id))

@app.route('/delete_review/<int:review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
    # Fetch the review or return 404 if not found
    review = Review.query.get_or_404(review_id)
    
    # Check if the current user is the owner of the review
    if review.user_id == current_user.id:
        # Remove all flags associated with this review before deletion
        ReviewFlag.query.filter_by(review_id=review.id).delete()

        # Delete the review
        db.session.delete(review)
        db.session.commit()
        
    return redirect(url_for('institutions'))

@app.route('/edit_review/<int:review_id>', methods=['GET', 'POST'])
@login_required
def edit_review(review_id):
    review = Review.query.get(review_id)
    if review.user_id != current_user.id:
        return "You are not authorized to edit this review."
    if request.method == 'POST':
        review.content = request.form['content']
        db.session.commit()
        return redirect(url_for('institutions'))
    return render_template('edit_review.html', review=review)

def upgrade():
    op.add_column('user', sa.Column('is_admin', sa.Boolean(), nullable=False, default=False))

def downgrade():
    op.drop_column('user', 'is_admin')

@app.route('/flag_review/<int:review_id>', methods=['POST'])
@login_required
def flag_review(review_id, methods=['POST']):
    review = Review.query.get_or_404(review_id)
    
    # Check if the current user has already flagged this review
    existing_flag = ReviewFlag.query.filter_by(user_id=current_user.id, review_id=review_id).first()
    if existing_flag:
        return "You have already flagged this review."
    if review.flags is None:
        review.flags = 0
    review.flags += 1

    # Add a new flag
    #review.flags += 1
    if review.flags >= 3:
        review.flagged_as_fake = True
    
    new_flag = ReviewFlag(user_id=current_user.id, review_id=review_id)
    db.session.add(new_flag)
    db.session.commit()
    
    return redirect(url_for('institution', id=review.institution_id))

@app.route('/admin/flagged_reviews')
@login_required
def flagged_reviews():
    if not current_user.is_admin:  # Assuming you have an is_admin property for users
        return redirect(url_for('home'))

    flagged_reviews = Review.query.filter_by(flagged_as_fake=True).all()
    return render_template('flagged_reviews.html', reviews=flagged_reviews)

@app.route('/upvote_review/<int:review_id>', methods=['POST'])
@login_required
def upvote_review(review_id):
    review = Review.query.get(review_id)
    if review:
        existing_vote = UserVotes.query.filter_by(user_id=current_user.id, review_id=review_id).first()

        if existing_vote:
            if existing_vote.vote_type == 'upvote':
                db.session.delete(existing_vote)  # Remove the upvote if it's clicked again (toggle)
            else:
                existing_vote.vote_type = 'upvote'  # Change a downvote to an upvote
        else:
            new_vote = UserVotes(user_id=current_user.id, review_id=review_id, vote_type='upvote')
            db.session.add(new_vote)
        
        db.session.commit()

    return redirect(url_for('institution', id=review.institution_id))

@app.route('/downvote_review/<int:review_id>', methods=['POST'])
@login_required
def downvote_review(review_id):
    review = Review.query.get(review_id)
    if review:
        existing_vote = UserVotes.query.filter_by(user_id=current_user.id, review_id=review_id).first()

        if existing_vote:
            if existing_vote.vote_type == 'downvote':
                db.session.delete(existing_vote)  # Remove the downvote if it's clicked again (toggle)
            else:
                existing_vote.vote_type = 'downvote'  # Change an upvote to a downvote
        else:
            new_vote = UserVotes(user_id=current_user.id, review_id=review_id, vote_type='downvote')
            db.session.add(new_vote)
        
        db.session.commit()

    return redirect(url_for('institution', id=review.institution_id))
@app.route('/about')
def about_us():
    return render_template('about_us.html')

@app.route('/services')
def services():
    return render_template('services.html')
import sqlite3
from flask import Flask, render_template

#app = Flask(__name__)
@app.route('/institutions')
def get_institution_ratings():
    conn = sqlite3.connect('your_database.db')  # Replace with your actual database
    cursor = conn.cursor()
    
    # Query to calculate sentiment-based rating for each institution
    cursor.execute("""
        SELECT 
            institution_id,
            SUM(CASE WHEN sentiment = 'positive' THEN 5 ELSE 0 END) AS positive_score,
            SUM(CASE WHEN sentiment = 'neutral' THEN 3 ELSE 0 END) AS neutral_score,
            SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative_score,
            COUNT(*) AS total_reviews
        FROM reviews
        GROUP BY institution_id;
    """)
    
    results = cursor.fetchall()
    
    institution_ratings = []
    for row in results:
        institution_id, positive_score, neutral_score, negative_score, total_reviews = row
        if total_reviews > 0:
            weighted_sum = positive_score + neutral_score + negative_score
            average_rating = weighted_sum / total_reviews
        else:
            average_rating = None  # No reviews available
        institution_ratings.append({
            'institution_id': institution_id,
            'average_rating': average_rating
        })
    
    conn.close()
    return institution_ratings

@app.route('/institutions')
def show_institutions():
    # Fetch institution ratings
    institution_ratings = get_institution_ratings()
    
    # Fetch institutions data (assuming a function to get all institution data)
    institutions = get_institutions()  # Replace with your function that fetches institution data

    # Merge ratings into each institution dictionary
    for institution in institutions:
        institution_id = institution['id']
        rating_data = next((rating for rating in institution_ratings if rating['institution_id'] == institution_id), None)
        institution['average_rating'] = rating_data['average_rating'] if rating_data else 'No ratings yet'
    print(institutions) 
    return render_template('institutions.html', institutions=institutions)



#app = Flask(__name__)

# Faster but less accurate
def calc(loc1, loc2):
    geolocator = Nominatim(user_agent='distance_calculator')
    loc1 = geolocator.geocode(loc1)
    loc2 = geolocator.geocode(loc2)

    if loc1 and loc2:
        d = distance((loc1.latitude, loc1.longitude), (loc2.latitude, loc2.longitude))
        return d.km
    return None

# Slower but more accurate
def driver_distance(loc1, loc2):
    options = Options()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)
    geolocator = Nominatim(user_agent='distance_calculator')
    loc1 = geolocator.geocode(loc1)
    loc2 = geolocator.geocode(loc2)
    url = f'https://distancecalculator.globefeed.com/India_Distance_Result.asp?fromlat={loc1.latitude}&fromlng={loc1.longitude}&tolat={loc2.latitude}&tolng={loc2.longitude}'
    driver.get(url)
    try:
        WebDriverWait(driver, 100).until(
            lambda d: d.find_element(By.XPATH, '//*[@id="drvDistance"]').text != "Calculating"
        )
        ele = driver.find_element(By.XPATH, '//*[@id="drvDistance"]')
        return ele.text
    finally:
        driver.quit()

@app.route('/calculate_distance', methods=['POST'])
def calculate_distance():
    data = request.get_json()
    loc1 = data.get('user_location')
    loc2 = data.get('institution_location')
    
    # You can choose which function to use here
    distance_value = calc(loc1, loc2)  # Use `calc` function (faster)
    # distance_value = driver_distance(loc1, loc2)  # Use `driver_distance` function (slower)
    
    if distance_value:
        transport_mode = suggest_transport_mode(distance_value)
        return jsonify({'distance': distance_value, 'transport_mode': transport_mode})
    else:
        return jsonify({'error': 'Could not calculate distance'}), 400
def suggest_transport_mode(distance):
    # Logic to suggest modes of transport based on distance
    if distance < 1:
        return "Walking is a great option!"
    elif distance < 5:
        return "Consider riding a bicycle."
    elif distance < 20:
        return "Driving bike would be convenient."
    elif distance < 50:
        return "You might want to take a car ."
    elif distance < 75:
        return "Public transport is a good choice."
    elif distance < 100:
        return "You might want to take a bus ."
    else:
        return "You might want to take public Train service."
# Main function to run the app
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)








