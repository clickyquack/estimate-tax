# To run: python sample_data.py

import random
from faker import Faker
from app import create_app
from app.extensions import db
from app.models import Firm, Role, User, Client

fake = Faker()
app = create_app()

def generate_sample_data():
    with app.app_context():
        print("Wiping and rebuilding...")
        db.drop_all()
        db.create_all()

        # Define Permanent Roles
        role_names = ['Developer', 'SysAdmin', 'Admin', 'Accountant']
        roles = {}
        for name in role_names:
            r = Role(name=name)
            db.session.add(r)
            roles[name] = r
        db.session.commit()

        # Generate Test Firm
        test_firm = Firm(
            name="Test Firm", 
            email="test@test.com"
        )
        db.session.add(test_firm)
        db.session.commit()


        # Sample Users for the test firm
        # Developer User
        developer = User(
            name="Test Developer",
            email="developer@test.com",
            role_id=roles['Developer'].id,
            firm_id=test_firm.id
        )
        developer.set_password('developer')
        
        # SysAdmin User
        sysadmon = User(
            name="Test SysAdmin",
            email="sysadmin@test.com",
            role_id=roles['SysAdmin'].id,
            firm_id=test_firm.id
        )
        sysadmon.set_password('sysadmin')

        # Admin User
        admin = User(
            name="Test Admin",
            email="admin@test.com",
            role_id=roles['Admin'].id,
            firm_id=test_firm.id
        )
        admin.set_password('admin')
        
        # Standard Accountant (Alex)
        Accountant1 = User(
            name="Test Accountant 1",
            email="accountant1@test.com",
            role_id=roles['Accountant'].id,
            firm_id=test_firm.id
        )
        Accountant1.set_password('accountant')

        Accountant2 = User(
            name="Test Accountant 2",
            email="accountant2@test.com",
            role_id=roles['Accountant'].id,
            firm_id=test_firm.id
        )
        Accountant2.set_password('accountant')

        db.session.add_all([developer, sysadmon, admin, Accountant1, Accountant2])
        db.session.commit()


        # Clients generated with Faker
        for _ in range(30):

            if random.random() > 0.5:
                id_format = "##-#######"  # EIN
            else:
                id_format = "###-##-####" # SSN`
                
            client = Client(
                name=fake.company() if id_format == "##-#######" else fake.name(),
                email=fake.company_email(),
                tax_id=fake.numerify(text=id_format),
                firm_id=test_firm.id
            )
            # Randomly assign to either Accountant
            client.users.append(random.choice([Accountant1, Accountant2]))
            db.session.add(client)

        db.session.commit()
        print("Sample data initialized.")

if __name__ == "__main__":
    generate_sample_data()