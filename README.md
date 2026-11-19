# DRC Vaccine supply chain

A professional Flask-based vaccine supply chain management application for hospital and Ministry workflows.

## Features

- Two-role login flow: Ministry Admin and Hospital / Health Centre
- Facility registration with pending approval workflow
- Vaccine catalogue management for the Ministry
- Vaccine catalogue create, read, update, activate/deactivate, and permanent delete actions
- Batch-based inventory tracking and stock alerts
- Vaccine usage recording and automatic stock deduction
- Hospital vaccine request handling and status tracking
- Transfer coordination and confirmation workflow
- Messaging and notification support
- Dashboard summaries and reports

## Tech stack

- Frontend: HTML5, CSS3, JavaScript
- Backend: Python + Flask
- Database: MongoDB via PyMongo
- Fallback for local testing: mongomock when no MongoDB server is available

## Run the application

1. Install dependencies:
   python -m pip install -r requirements.txt
2. Start the app (served by Waitress, without Flask's debug reloader):
   python app.py
3. Open the browser at:
   http://localhost:5000/

## Default admin credentials

- Username: admin
- Password: admin123

## Notes

- If MongoDB is not running locally, the app automatically falls back to an in-memory mock database so the app can still be used for demos and testing.
- To connect to a real MongoDB instance, set the `MONGO_URI` environment variable before starting the app.
- The app uses Waitress as its WSGI server on Windows to avoid Flask development-server reloader/socket shutdown errors. Do not expose the demo credentials or mock-database mode as a production deployment.
