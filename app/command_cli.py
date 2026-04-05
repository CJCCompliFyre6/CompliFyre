# your_project/cli_commands.py
import csv
import os
import click
from flask.cli import with_appcontext
from sqlalchemy import func # Import func for current_timestamp
from app.models.user import Roles # Adjust import based on your models file location
from app.models.organization import Country, State, City, OrganizationDepartments, OrganizationType ,Constitution# Import OrganizationDepartments
from app import db

def register_cli_commands(app):
    """Registers custom CLI commands with the Flask application."""

    @app.cli.command("seed")
    @with_appcontext
    def seed_command():
        """Seeds the database with initial data including India, states, and cities, ADMIN role, and organization departments from CSV."""
        print("Starting database seeding process...")

        # 1. Seed Country: India
        # Ensure 'India' exists or get its object
        india = Country.query.filter_by(name="India").first()
        if india is None:
            print("Seeding 'India' country...")
            india = Country(name="India", iso_code="IN", phone_code="+91")
            db.session.add(india)
            db.session.flush() # Flush to get the country_id if needed immediately for states
            print("India country seeded.")
        else:
            print("India country already exists, skipping.")

        # 2. Seed Roles: ADMIN, COMPLIFYRE, AUDITOR, RE
        roles_to_seed = [
            {"name": "ADMIN", "description": "Administrator role with full permissions"},
            {"name": "COMPLIFYRE", "description": "CompliFyRe user role"},
            {"name": "AUDITOR", "description": "Auditor role"},
            {"name": "RE", "description": "Regular Employee role"}
        ]

        for role_data in roles_to_seed:
            if Roles.query.filter_by(name=role_data["name"]).first() is None:
                print(f"Seeding '{role_data['name']}' role...")
                new_role = Roles(name=role_data["name"], description=role_data["description"])
                db.session.add(new_role)
                print(f"{role_data['name']} role added to session.")
            else:
                print(f"{role_data['name']} role already exists, skipping.")
        
        db.session.commit() # Commit country and roles, so their IDs are available.

        # Determine the project root for data files
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.join(current_dir, '..') # Go up one level from 'your_project'

        # 3. Seed States and Cities from CSV
        states_cities_csv_file_path = os.path.join(project_root, 'data', 'india_states_cities.csv')

        # Fallback if data is inside the package (e.g., your_project/data)
        if not os.path.exists(states_cities_csv_file_path):
             states_cities_csv_file_path = os.path.join(current_dir, 'data', 'indian_states_and_cities.csv')


        if not os.path.exists(states_cities_csv_file_path):
            print(f"Error: States/Cities CSV file not found at {states_cities_csv_file_path}. Please ensure 'data/indian_states_and_cities.csv' exists.")
            print("Current working directory:", os.getcwd())
        else:
            print(f"Loading states and cities from {states_cities_csv_file_path}...")
            added_states = {} # To keep track of states processed in this run

            try:
                with open(states_cities_csv_file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row_num, row in enumerate(reader, 2):
                        state_name = row.get('State', '').strip()
                        city_name = row.get('City', '').strip()

                        if not state_name or not city_name:
                            continue

                        state_obj = added_states.get(state_name)
                        if state_obj is None:
                            state_obj = State.query.filter_by(state_name=state_name, country_id=india.country_id).first()
                            if state_obj is None:
                                state_obj = State(state_name=state_name, country_id=india.country_id)
                                db.session.add(state_obj)
                            added_states[state_name] = state_obj

                        db.session.flush() # Ensure state_obj has an ID if it was newly added

                        city_obj = City.query.filter_by(name=city_name, state_id=state_obj.state_id).first()
                        if city_obj is None:
                            city_obj = City(name=city_name, state_id=state_obj.state_id)
                            db.session.add(city_obj)

                

                db.session.commit() # Commit all new states and cities at once
                print("States and Cities data seeding complete.")
        

            except FileNotFoundError:
                print(f"Error: The CSV file was not found at {states_cities_csv_file_path}")
            except Exception as e:
                db.session.rollback() # Rollback on error
                print(f"An error occurred during CSV processing for states/cities: {e}")
                import traceback
                traceback.print_exc() # Print full traceback for debugging


        # 4. Seed Organization Departments, Processes, and Sub-Processes from CSV
        print("Seeding Organization Departments, Processes, and Sub-Processes from CSV...")
        departments_csv_file_path = os.path.join(project_root, 'data', 'department.csv')

        if not os.path.exists(departments_csv_file_path):
            # Fallback if data is inside the package (e.g., your_project/data)
            departments_csv_file_path = os.path.join(current_dir, 'data', 'department.csv')

        if not os.path.exists(departments_csv_file_path):
            print(f"Error: Organization Departments CSV file not found at {departments_csv_file_path}. Please ensure 'data/department.csv' exists.")
            print("Current working directory:", os.getcwd())
        else:
            try:
                with open(departments_csv_file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row_num, row in enumerate(reader, 2):
                        dept_name = row.get('Department', '').strip()
                        proc_name = row.get('Process', '').strip()
                        sub_proc = row.get('Sub-Process', '').strip()

                        if not dept_name or not proc_name or not sub_proc:
                            # print(f"Skipping row {row_num}: Incomplete department data (Department: '{dept_name}', Process: '{proc_name}', Sub-Process: '{sub_proc}')")
                            continue

                        # Check if the entry already exists to prevent duplicates
                        existing_entry = OrganizationDepartments.query.filter_by(
                            department_name=dept_name,
                            process_name=proc_name,
                            sub_process=sub_proc
                        ).first()

                        if existing_entry is None:
                            new_department_entry = OrganizationDepartments(
                                department_name=dept_name,
                                process_name=proc_name,
                                sub_process=sub_proc
                            )
                            db.session.add(new_department_entry)
                        # else:
                            # print(f"Skipping existing department entry: {dept_name} - {proc_name} - {sub_proc}")

                db.session.commit()
                print("Organization Departments, Processes, and Sub-Processes seeding complete.")

            except FileNotFoundError: # This block might not be hit if os.path.exists check is robust
                print(f"Error: The CSV file for departments was not found at {departments_csv_file_path}")
            except Exception as e:
                db.session.rollback()
                print(f"An error occurred during department seeding from CSV: {e}")
                import traceback
                traceback.print_exc()
        
    # 4. Seed constitution type 
        print("Seeding Constitution Types CSV...")
        constitution_types_csv_file_path = os.path.join(project_root, 'data', 'constitution_types.csv')

        if not os.path.exists(constitution_types_csv_file_path):
            # Fallback if data is inside the package (e.g., your_project/data)
            constitution_types_csv_file_path = os.path.join(current_dir, 'data', 'constitution_types.csv')

        if not os.path.exists(constitution_types_csv_file_path):
            print(f"Error: Constitution Types CSV file not found at {constitution_types_csv_file_path}. Please ensure 'data/constitution_types.csv' exists.")
            print("Current working directory:", os.getcwd())
        else:
            try:
                with open(constitution_types_csv_file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row_num, row in enumerate(reader, 2):
                        constitution_type = row.get('constitution_type', '').strip()
                        

                        if not constitution_type:
                            # print(f"Skipping row {row_num}: Incomplete organization type data (Category: '{category}', Subcategory: '{subcategory}')")
                            continue

                        # Check if the entry already exists to prevent duplicates
                        existing_entry = Constitution.query.filter_by(
                            name=constitution_type
                        ).first()

                        if existing_entry is None:
                            new_type_entry = Constitution(
                                name=constitution_type
                            )
                            db.session.add(new_type_entry)
                        # else:
                            # print(f"Skipping existing organization type entry: {category} - {subcategory}")

                db.session.commit()
                print("Constitution Types seeding complete.")

            except FileNotFoundError:
                print(f"Error: The CSV file for constitution types was not found at {constitution_types_csv_file_path}")
            except Exception as e:
                db.session.rollback()
                print(f"An error occurred during constitution type seeding from CSV: {e}")


        print("Seeding Organization Types CSV...")
        types_csv_file_path = os.path.join(project_root, 'data', 'category_subcategory_mapping_cleaned.csv')

        if not os.path.exists(types_csv_file_path):
            # Fallback if data is inside the package (e.g., your_project/data)
            types_csv_file_path = os.path.join(current_dir, 'data', 'category_subcategory_mapping_cleaned.csv')

        if not os.path.exists(types_csv_file_path):
            print(f"Error: Organization Types CSV file not found at {types_csv_file_path}. Please ensure 'data/category_subcategory_mapping_cleaned.csv' exists.")
            print("Current working directory:", os.getcwd())
        else:
            try:
                with open(types_csv_file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row_num, row in enumerate(reader, 2):
                        category = row.get('category', '').strip()
                        subcategory = row.get('subcategory', '').strip()

                        if not category or not subcategory:
                            # print(f"Skipping row {row_num}: Incomplete organization type data (Category: '{category}', Subcategory: '{subcategory}')")
                            continue

                        # Check if the entry already exists to prevent duplicates
                        existing_entry = OrganizationType.query.filter_by(
                            category=category,
                            name=subcategory
                        ).first()

                        if existing_entry is None:
                            new_type_entry = OrganizationType(
                                category=category,
                                name=subcategory
                            )
                            db.session.add(new_type_entry)
                        # else:
                            # print(f"Skipping existing organization type entry: {category} - {subcategory}")

                db.session.commit()
                print("Organization Types seeding complete.")

            except FileNotFoundError:
                print(f"Error: The CSV file for organization types was not found at {types_csv_file_path}")
            except Exception as e:
                db.session.rollback()
                print(f"An error occurred during organization type seeding from CSV: {e}")
        


                
        print("Database seeding process finished.")
