from app import app, db
from models import User


def create_users():
    with app.app_context():
        # Show which DB we are writing to (password redacted)
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        shown = uri.split("@")[-1] if "@" in uri else uri
        print(f"🔌 Seeding DB: {shown}")

        users_to_create = [
            {
                "username": "tech1",
                "password": "TechOnePassword123!",
                "full_name": "Technician One",
                "role": "technician",
            },
            {
                "username": "tech2",
                "password": "TechTwoPassword123!",
                "full_name": "Technician Two",
                "role": "technician",
            },
            {
                "username": "user1",
                "password": "UserOnePassword123!",
                "full_name": "Standard User",
                "role": "user",
            },
        ]

        for u in users_to_create:
            existing = User.query.filter_by(username=u["username"]).first()
            if existing:
                # Repair: re-hash in case it was previously seeded with werkzeug
                existing.set_password(u["password"])
                existing.is_active = True
                existing.full_name = u["full_name"]
                existing.role = u["role"]
                print(f"🔄 Re-hashed existing user: {u['username']}")
                continue

            new_user = User(
                username=u["username"],
                full_name=u["full_name"],
                role=u["role"],
                is_active=True,
            )
            new_user.set_password(u["password"])  # argon2 — matches models.py
            db.session.add(new_user)
            print(f"✅ Created {u['role']} account: {u['username']}")

        db.session.commit()
        print(f"\nDone. Total users in DB: {User.query.count()}")


if __name__ == "__main__":
    create_users()