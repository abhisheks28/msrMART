from app import create_app, init_db_and_admin, login_manager
from models import User

app = create_app()

with app.app_context():
    init_db_and_admin(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

if __name__ == '__main__':
    app.run(debug=True)
