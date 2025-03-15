from app import app, db, Institution

with app.app_context():
    institutions = Institution.query.all()
    for institution in institutions:
        print(f"Name: {institution.name}, Location: {institution.location}, Description: {institution.description}")
