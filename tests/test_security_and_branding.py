import unittest

from app import create_app
from models import db, User, Item, Area


class SecurityAndBrandingTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SECRET_KEY="test-secret-key",
        )

        with self.app.app_context():
            db.drop_all()
            db.create_all()

            area = Area(name="Main Lab", sort_order=1)
            db.session.add(area)
            db.session.flush()

            item = Item(
                inventory_id="APP-001",
                name="Microscope",
                category="Apparatus",
                area_id=area.id,
                opening_qty=5,
                unit="each",
                location="Bench A",
                min_level=2,
                reorder_level=3,
            )
            db.session.add(item)
            db.session.commit()
            self.item_id = item.id

            admin = User(username="admin_user", role="admin", full_name="Admin User")
            admin.set_password("StrongPass!123")
            technical = User(username="tech_user", role="technician", full_name="Tech User")
            technical.set_password("StrongPass!123")
            viewer = User(username="viewer_user", role="viewer", full_name="Viewer User")
            viewer.set_password("StrongPass!123")
            db.session.add_all([admin, technical, viewer])
            db.session.commit()

            self.admin_user = admin.username
            self.tech_user = technical.username
            self.viewer_user = viewer.username

    def test_admin_can_open_edit_page(self):
        with self.app.test_client() as client:
            login = client.post(
                "/login",
                data={"username": self.admin_user, "password": "StrongPass!123"},
                follow_redirects=True,
            )
            self.assertEqual(login.status_code, 200)
            response = client.get(f"/item/{self.item_id}/edit")
            self.assertIn(response.status_code, (200, 302))

    def test_technician_cannot_edit_inventory_items(self):
        with self.app.test_client() as client:
            client.post(
                "/login",
                data={"username": self.tech_user, "password": "StrongPass!123"},
                follow_redirects=True,
            )
            response = client.get(f"/item/{self.item_id}/edit")
            self.assertIn(response.status_code, (302, 403))

    def test_login_page_has_nprdc_branding(self):
        with self.app.test_client() as client:
            response = client.get("/login")
            self.assertEqual(response.status_code, 200)
            self.assertIn("National Pathology Research and Diagnostic Centre", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
