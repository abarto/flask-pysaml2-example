from flask_login import UserMixin

from . import db


class User(db.Model, UserMixin):
    email = db.Column(db.String(128), primary_key=True)
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))

    def get_id(self):
        return self.email

    def __repr__(self):
        return f'<User {self.email}>'
