from __future__ import annotations

from flask_login import UserMixin

from . import db


class User(db.Model, UserMixin):  # type: ignore[name-defined,misc]
    email = db.Column(db.String(128), primary_key=True)
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))

    def get_id(self) -> str:
        return self.email

    def __repr__(self) -> str:
        return f'<User {self.email}>'
