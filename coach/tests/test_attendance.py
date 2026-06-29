import pytest
from coach.app import app
from coach.extensions import db
from coach.models import Team, Player


@pytest.fixture
def client():
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with app.app_context():
        db.drop_all()
        db.create_all()
        team = Team(name='Test Team')
        db.session.add(team)
        db.session.commit()
        player = Player(team_id=team.id, name='Test Player', position='F')
        db.session.add(player)
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_dochazka_page_is_available(client):
    with client.session_transaction() as sess:
        sess['team_id'] = 1
        sess['team_role'] = 'coach'
        sess['team_login'] = True

    response = client.get('/dochazka')
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Dochazka' in text or 'Docházka' in text
