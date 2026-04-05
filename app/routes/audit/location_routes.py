from flask import Blueprint, jsonify,request
from app.models.organization import Country
from app.models.organization import State
from app.models.organization import City

location_bp = Blueprint("location_bp", __name__)

@location_bp.route("/countries", methods=["GET"])
def get_countries():
    countries = Country.query.order_by(Country.name).all()
    return jsonify([
        {"id": country.country_id, "name": country.name}
        for country in countries
    ])



@location_bp.route("/states/<int:country_id>", methods=["GET"])
def get_states(country_id):
    states = State.query.filter_by(country_id=country_id).order_by(State.state_name).all()
    return jsonify([
        {"id": state.state_id, "name": state.state_name}
        for state in states
    ])

@location_bp.route("/cities/<int:state_id>", methods=["GET"])
def get_cities(state_id):
    cities = City.query.filter_by(state_id=state_id).order_by(City.name).all()
    return jsonify([
        {"id": city.city_id, "name": city.name}
        for city in cities
    ])
