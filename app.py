import os
import re
from datetime import datetime

from bson import ObjectId
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from pymongo import MongoClient
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import mongomock
except Exception:  # pragma: no cover
    mongomock = None

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "vaccine-supply-secret")

mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/vaccine_supply_chain")

try:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=1500)
    client.admin.command("ping")
    db = client.get_default_database()
    app.config["DB_MODE"] = "mongodb"
except Exception:
    if os.getenv("MONGO_URI"):
        raise RuntimeError("Could not connect to MongoDB Atlas. Check your MONGO_URI and network access.")

    if mongomock is None:
        raise RuntimeError("MongoDB is unavailable and mongomock is not installed.")

    client = mongomock.MongoClient()
    db = client.vaccine_supply_chain
    app.config["DB_MODE"] = "mock"


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.users.find_one({"_id": ObjectId(user_id)})


def facility_from_user(user):
    if not user:
        return None
    facility_id = user.get("facility_id")
    if not facility_id:
        return None
    return db.facilities.find_one({"_id": ObjectId(facility_id)})


def get_vaccine_name(vaccine_id):
    vaccine = db.vaccines.find_one({"_id": ObjectId(vaccine_id)})
    return vaccine["name"] if vaccine else "Unknown vaccine"


def find_user_by_username(username):
    normalized_username = username.strip()
    if not normalized_username:
        return None
    return db.users.find_one(
        {"username": {"$regex": f"^{re.escape(normalized_username)}$", "$options": "i"}}
    )


def ensure_seed_data():
    if db.users.count_documents({}) == 0:
        db.users.insert_one(
            {
                "username": "admin",
                "password_hash": generate_password_hash("admin123"),
                "role": "ministry_admin",
                "full_name": "Ministry Administrator",
            }
        )

    if db.healthZones.count_documents({}) == 0:
        db.healthZones.insert_many(
            [
                {"name": "Central", "province": "Kigali City"},
                {"name": "North", "province": "Northern Province"},
                {"name": "East", "province": "Eastern Province"},
                {"name": "South", "province": "Southern Province"},
                {"name": "West", "province": "Western Province"},
            ]
        )

    if db.vaccines.count_documents({}) == 0:
        db.vaccines.insert_many(
            [
                {
                    "name": "Pfizer-BioNTech",
                    "manufacturer": "Pfizer",
                    "type": "mRNA",
                    "doses_required": 2,
                    "supplier": "WHO Supply Chain",
                    "description": "COVID-19 vaccine",
                    "status": "active",
                },
                {
                    "name": "Moderna",
                    "manufacturer": "Moderna",
                    "type": "mRNA",
                    "doses_required": 2,
                    "supplier": "Global Health Partners",
                    "description": "COVID-19 vaccine",
                    "status": "active",
                },
                {
                    "name": "AstraZeneca",
                    "manufacturer": "AstraZeneca",
                    "type": "Viral Vector",
                    "doses_required": 2,
                    "supplier": "GAVI",
                    "description": "COVID-19 vaccine",
                    "status": "active",
                },
                {
                    "name": "Johnson & Johnson",
                    "manufacturer": "Johnson & Johnson",
                    "type": "Viral Vector",
                    "doses_required": 1,
                    "supplier": "Global Health Partners",
                    "description": "Single-dose vaccine",
                    "status": "active",
                },
            ]
        )


@app.before_request
def setup_seed():
    ensure_seed_data()


@app.context_processor
def inject_defaults():
    return {
        "app_name": "DRC Vaccine supply chain",
        "now": datetime.utcnow,
        "user": current_user(),
    }


@app.route("/")
def index():
    if session.get("user_id"):
        user = current_user()
        if user and user.get("role") == "ministry_admin":
            return redirect(url_for("admin_dashboard"))
        if user and user.get("role") == "hospital":
            return redirect(url_for("hospital_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = find_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            if user.get("role") == "hospital":
                facility = db.facilities.find_one({"_id": ObjectId(user["facility_id"])})
                if not facility or facility.get("status") != "Active":
                    flash("Your facility registration is still pending approval.", "error")
                    return redirect(url_for("login"))
            session["user_id"] = str(user["_id"])
            if user.get("role") == "ministry_admin":
                flash("Welcome back, Ministry Admin.", "success")
                return redirect(url_for("admin_dashboard"))
            flash("Welcome back.", "success")
            return redirect(url_for("hospital_dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register_facility():
    if request.method == "POST":
        password = request.form.get("password", "")
        facility = {
            "facility_name": request.form.get("facility_name", "").strip(),
            "facility_type": request.form.get("facility_type", "Hospital"),
            "province": request.form.get("province", "").strip(),
            "health_zone": request.form.get("health_zone", "").strip(),
            "address": request.form.get("address", "").strip(),
            "contact_person": request.form.get("contact_person", "").strip(),
            "phone_number": request.form.get("phone_number", "").strip(),
            "registration_number": request.form.get("registration_number", "").strip(),
            "email": request.form.get("email", "").strip(),
            "status": "Pending Approval",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "approved_by": None,
        }

        username = request.form.get("username", "").strip()
        form_data = request.form
        if any(not (request.form.get(field, "").strip() if field != "password" else request.form.get(field, "")) for field in ["facility_name", "facility_type", "province", "health_zone", "address", "contact_person", "phone_number", "email", "username", "password"]):
            flash("Please complete all required fields.", "error")
            return render_template("register.html", form_data=form_data)

        if not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", username):
            flash("Username must be 3–30 characters and use only letters, numbers, dots, underscores or hyphens.", "error")
            return render_template("register.html", form_data=form_data)

        existing_user = find_user_by_username(username)
        if existing_user:
            existing_facility = None
            if existing_user.get("role") == "hospital" and existing_user.get("facility_id"):
                existing_facility = db.facilities.find_one({"_id": existing_user["facility_id"]})
            same_submission = (
                existing_facility
                and existing_facility.get("email", "").strip().casefold() == facility["email"].casefold()
                and existing_facility.get("facility_name", "").strip().casefold() == facility["facility_name"].casefold()
            )
            if same_submission:
                status = existing_facility.get("status", "Unknown")
                flash(f"This facility already has a registration ({status}). Please use the existing username to log in or contact the Ministry Admin.", "info")
                return redirect(url_for("login"))
            flash("That username is already in use. Please choose a different username.", "error")
            return render_template("register.html", form_data=form_data)

        facility["username"] = username.lower()
        facility_id = db.facilities.insert_one(facility).inserted_id
        db.users.insert_one(
            {
                "username": username.lower(),
                "password_hash": generate_password_hash(password),
                "role": "hospital",
                "facility_id": facility_id,
                "full_name": facility["contact_person"],
            }
        )
        db.notifications.insert_one(
            {
                "title": "New facility registration",
                "message": f"{facility['facility_name']} has submitted a registration request.",
                "type": "facility_registration",
                "created_at": datetime.utcnow(),
                "read_by_admin": False,
            }
        )
        flash("Registration submitted successfully. Awaiting Ministry approval.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/register/check-username")
def check_username():
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"available": False, "message": ""})
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", username):
        return jsonify({"available": False, "message": "Use 3–30 letters, numbers, dots, underscores or hyphens."})
    available = find_user_by_username(username) is None
    return jsonify({
        "available": available,
        "message": "Username is available." if available else "Username is already in use. Please choose another.",
    })


@app.route("/admin")
def admin_redirect():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/dashboard")
def admin_dashboard():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    facilities = list(db.facilities.find({}))
    vaccines = list(db.vaccines.find({}))
    total_stock = 0
    for record in db.inventory.find({}):
        total_stock += int(record.get("quantity_available", 0))

    pending_registrations = db.facilities.count_documents({"status": "Pending Approval"})
    low_stock_alerts = sum(
        1
        for record in db.inventory.find({})
        if 0 < int(record.get("quantity_available", 0)) <= int(record.get("minimum_stock", 0))
    )
    out_of_stock = db.inventory.count_documents({"quantity_available": 0})
    pending_requests = db.vaccineRequests.count_documents({"status": {"$in": ["Pending", "Under Review"]}})
    low_stock_facilities = set()
    for record in db.inventory.find({"quantity_available": {"$lte": 0}}):
        facility = db.facilities.find_one({"_id": ObjectId(record["facility_id"])})
        if facility:
            low_stock_facilities.add(facility["facility_name"])

    recent_activities = list(db.auditLogs.find({}).sort("created_at", -1).limit(5))
    recent_transfers = list(db.transfers.find({}).sort("created_at", -1).limit(5))
    pending_notifications = list(db.notifications.find({"read_by_admin": False}).sort("created_at", -1).limit(8))

    stats = {
        "total_facilities": len(facilities),
        "pending_registrations": pending_registrations,
        "total_vaccine_types": len(vaccines),
        "total_available_stock": total_stock,
        "low_stock_alerts": low_stock_alerts,
        "out_of_stock": out_of_stock,
        "pending_requests": pending_requests,
        "recent_activities": recent_activities,
        "recent_transfers": recent_transfers,
        "notifications": pending_notifications,
    }
    return render_template("admin_dashboard.html", stats=stats)


@app.route("/admin/facilities", methods=["GET", "POST"])
def admin_facilities():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        facility = {
            "facility_name": request.form.get("facility_name", "").strip(),
            "facility_type": request.form.get("facility_type", "Hospital"),
            "province": request.form.get("province", "").strip(),
            "health_zone": request.form.get("health_zone", "").strip(),
            "address": request.form.get("address", "").strip(),
            "contact_person": request.form.get("contact_person", "").strip(),
            "phone_number": request.form.get("phone_number", "").strip(),
            "registration_number": request.form.get("registration_number", "").strip(),
            "email": request.form.get("email", "").strip(),
            "status": "Active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        if not password:
            flash("Password is required for manual facility creation.", "error")
        elif not username or not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", username):
            flash("Enter a valid username (3–30 letters, numbers, dots, underscores or hyphens).", "error")
        elif find_user_by_username(username):
            flash("That username is already in use. Please choose a different username.", "error")
        else:
            facility_id = db.facilities.insert_one(facility).inserted_id
            db.users.insert_one(
                {
                    "username": username.lower(),
                    "password_hash": generate_password_hash(password),
                    "role": "hospital",
                    "facility_id": facility_id,
                    "full_name": facility["contact_person"],
                }
            )
            db.auditLogs.insert_one({
                "action": "create_facility",
                "details": f"Facility {facility['facility_name']} created manually.",
                "created_at": datetime.utcnow(),
            })
            flash("Facility added successfully.", "success")

    query = request.args.get("q", "")
    province = request.args.get("province", "")
    health_zone = request.args.get("health_zone", "")
    filters = {}
    if query:
        filters["$or"] = [
            {"facility_name": {"$regex": query, "$options": "i"}},
            {"province": {"$regex": query, "$options": "i"}},
            {"health_zone": {"$regex": query, "$options": "i"}},
        ]
    if province:
        filters["province"] = province
    if health_zone:
        filters["health_zone"] = health_zone

    facilities = list(db.facilities.find(filters).sort("facility_name", 1))
    return render_template("admin_facilities.html", facilities=facilities)


@app.route("/admin/facility/<facility_id>/update-status", methods=["POST"])
def update_facility_status(facility_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    new_status = request.form.get("status")
    reason = request.form.get("reason", "")
    db.facilities.update_one({"_id": ObjectId(facility_id)}, {"$set": {"status": new_status, "updated_at": datetime.utcnow()}})
    db.auditLogs.insert_one({
        "action": "facility_status_update",
        "facility_id": facility_id,
        "status": new_status,
        "reason": reason,
        "created_at": datetime.utcnow(),
    })
    flash(f"Facility status updated to {new_status}.", "success")
    return redirect(url_for("admin_facilities"))


@app.route("/admin/registration-requests")
def registration_requests():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    facilities = list(db.facilities.find({"status": "Pending Approval"}).sort("created_at", -1))
    all_f = list(db.facilities.find({"status": {"$ne": "Pending Approval"}}).sort("updated_at", -1))
    return render_template("admin_registration_requests.html", facilities=facilities, reviewed=all_f)


@app.route("/admin/registration-requests/<facility_id>/approve", methods=["POST"]) 
def approve_registration(facility_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    db.facilities.update_one({"_id": ObjectId(facility_id)}, {"$set": {"status": "Active", "updated_at": datetime.utcnow()}})
    db.notifications.insert_one({
        "title": "Registration approved",
        "message": "Your facility registration has been approved and you may now log in.",
        "facility_id": facility_id,
        "type": "approval",
        "created_at": datetime.utcnow(),
    })
    db.auditLogs.insert_one({
        "action": "approve_registration",
        "facility_id": facility_id,
        "created_at": datetime.utcnow(),
    })
    flash("Registration approved.", "success")
    return redirect(url_for("registration_requests"))


@app.route("/admin/registration-requests/<facility_id>/reject", methods=["POST"]) 
def reject_registration(facility_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    reason = request.form.get("reason", "No reason provided.")
    db.facilities.update_one({"_id": ObjectId(facility_id)}, {"$set": {"status": "Rejected", "rejection_reason": reason, "updated_at": datetime.utcnow()}})
    db.notifications.insert_one({
        "title": "Registration rejected",
        "message": f"Your facility registration was rejected. Reason: {reason}",
        "facility_id": facility_id,
        "type": "rejection",
        "created_at": datetime.utcnow(),
    })
    flash("Registration rejected.", "success")
    return redirect(url_for("registration_requests"))


def vaccine_form_data():
    vaccine = {
        "name": request.form.get("name", "").strip(),
        "manufacturer": request.form.get("manufacturer", "").strip(),
        "type": request.form.get("type", "").strip(),
        "doses_required": request.form.get("doses_required", "").strip(),
        "dosage": request.form.get("dosage", "").strip(),
        "storage_requirements": request.form.get("storage_requirements", "").strip(),
        "supplier": request.form.get("supplier", "").strip(),
        "description": request.form.get("description", "").strip(),
        "status": request.form.get("status", "active").strip().lower(),
    }
    try:
        vaccine["doses_required"] = int(vaccine["doses_required"])
    except ValueError:
        vaccine["doses_required"] = 0

    required_fields = ("name", "manufacturer", "type")
    if any(not vaccine[field] for field in required_fields) or vaccine["doses_required"] < 1:
        return vaccine, "Enter a vaccine name, manufacturer, type, and a valid dose count."
    if vaccine["status"] not in {"active", "inactive"}:
        return vaccine, "Choose a valid vaccine status."
    if any(len(vaccine[field]) > limit for field, limit in (
        ("name", 120), ("manufacturer", 120), ("type", 80), ("dosage", 120),
        ("storage_requirements", 500), ("supplier", 120), ("description", 2000),
    )):
        return vaccine, "Vaccine details exceed the allowed field length."
    return vaccine, None


@app.route("/admin/vaccines")
def admin_vaccines():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    vaccines = list(db.vaccines.find({}).sort("name", 1))
    return render_template("admin_vaccines.html", vaccines=vaccines)


@app.route("/admin/vaccines/new", methods=["GET", "POST"])
def add_vaccine():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    vaccine = {
        "name": "", "manufacturer": "", "type": "", "doses_required": 1,
        "dosage": "", "storage_requirements": "", "supplier": "",
        "description": "", "status": "active",
    }
    if request.method == "POST":
        vaccine, error = vaccine_form_data()
        duplicate = db.vaccines.find_one(
            {"name": {"$regex": f"^{re.escape(vaccine['name'])}$", "$options": "i"}}
        ) if vaccine["name"] else None
        if error:
            flash(error, "error")
        elif duplicate:
            flash("A vaccine with that name already exists.", "error")
        else:
            vaccine["created_at"] = datetime.utcnow()
            db.vaccines.insert_one(vaccine)
            db.auditLogs.insert_one({
                "action": "create_vaccine",
                "details": vaccine["name"],
                "created_at": datetime.utcnow(),
            })
            flash("Vaccine catalogue entry created.", "success")
            return redirect(url_for("admin_vaccines"))

    return render_template("admin_vaccine_edit.html", vaccine=vaccine, is_new=True)


@app.route("/admin/vaccines/<vaccine_id>/edit", methods=["GET", "POST"])
def edit_vaccine(vaccine_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    if not ObjectId.is_valid(vaccine_id):
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))

    vaccine = db.vaccines.find_one({"_id": ObjectId(vaccine_id)})
    if not vaccine:
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))

    if request.method == "POST":
        updated, error = vaccine_form_data()
        duplicate = db.vaccines.find_one({
            "_id": {"$ne": vaccine["_id"]},
            "name": {"$regex": f"^{re.escape(updated['name'])}$", "$options": "i"},
        }) if updated["name"] else None
        if error:
            flash(error, "error")
        elif duplicate:
            flash("A vaccine with that name already exists.", "error")
        else:
            db.vaccines.update_one({"_id": vaccine["_id"]}, {"$set": {**updated, "updated_at": datetime.utcnow()}})
            db.auditLogs.insert_one({
                "action": "update_vaccine",
                "details": updated["name"],
                "created_at": datetime.utcnow(),
            })
            flash("Vaccine catalogue entry updated.", "success")
            return redirect(url_for("admin_vaccines"))

        vaccine.update(updated)
        return render_template("admin_vaccine_edit.html", vaccine=vaccine, is_new=False)

    return render_template("admin_vaccine_edit.html", vaccine=vaccine, is_new=False)


@app.route("/admin/vaccines/<vaccine_id>")
def view_vaccine(vaccine_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    if not ObjectId.is_valid(vaccine_id):
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))
    vaccine = db.vaccines.find_one({"_id": ObjectId(vaccine_id)})
    if not vaccine:
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))
    return render_template("admin_vaccine_detail.html", vaccine=vaccine)


@app.route("/admin/vaccines/<vaccine_id>/status", methods=["POST"])
def toggle_vaccine_status(vaccine_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    if not ObjectId.is_valid(vaccine_id):
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))

    vaccine = db.vaccines.find_one({"_id": ObjectId(vaccine_id)})
    if not vaccine:
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))
    new_status = "active" if vaccine.get("status") != "active" else "inactive"
    db.vaccines.update_one(
        {"_id": vaccine["_id"]},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}},
    )
    db.auditLogs.insert_one({
        "action": "restore_vaccine" if new_status == "active" else "archive_vaccine",
        "details": vaccine["name"],
        "created_at": datetime.utcnow(),
    })
    flash(f"Vaccine {new_status}.", "success")
    return redirect(url_for("admin_vaccines"))


@app.route("/admin/vaccines/<vaccine_id>/delete", methods=["POST"])
def delete_vaccine(vaccine_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    if not ObjectId.is_valid(vaccine_id):
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))

    vaccine = db.vaccines.find_one({"_id": ObjectId(vaccine_id)})
    if not vaccine:
        flash("Vaccine not found.", "error")
        return redirect(url_for("admin_vaccines"))

    db.vaccines.delete_one({"_id": vaccine["_id"]})
    db.auditLogs.insert_one({
        "action": "delete_vaccine",
        "details": vaccine["name"],
        "created_at": datetime.utcnow(),
    })
    flash("Vaccine permanently deleted. Historical records remain unchanged.", "success")
    return redirect(url_for("admin_vaccines"))


@app.route("/admin/inventory")
def admin_inventory():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    records = []
    for item in db.inventory.find({}).sort("facility_name", 1):
        facility = db.facilities.find_one({"_id": ObjectId(item["facility_id"])})
        vaccine = db.vaccines.find_one({"_id": ObjectId(item["vaccine_id"])})
        status = "Available"
        if int(item.get("quantity_available", 0)) <= 0:
            status = "Out of Stock"
        elif int(item.get("quantity_available", 0)) <= int(item.get("minimum_stock", 0)):
            status = "Low Stock"
        records.append({
            "facility_name": facility["facility_name"] if facility else "Unknown",
            "province": facility.get("province", "") if facility else "",
            "health_zone": facility.get("health_zone", "") if facility else "",
            "vaccine_name": vaccine["name"] if vaccine else "Unknown",
            "manufacturer": vaccine.get("manufacturer", "") if vaccine else "",
            "batch_number": item.get("batch_number", ""),
            "quantity_available": int(item.get("quantity_available", 0)),
            "expiry_date": item.get("expiry_date", ""),
            "minimum_stock": item.get("minimum_stock", 0),
            "status": status,
        })
    return render_template("admin_inventory.html", records=records)


@app.route("/admin/vaccine-requests")
def admin_requests():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    requests = list(db.vaccineRequests.find({}).sort("date_submitted", -1))
    for req in requests:
        facility = db.facilities.find_one({"_id": ObjectId(req["facility_id"])})
        req["facility_name"] = facility["facility_name"] if facility else "Unknown"
        v = db.vaccines.find_one({"_id": ObjectId(req["vaccine_id"])})
        req["vaccine_name"] = v["name"] if v else "Unknown"
    return render_template("admin_requests.html", requests=requests)


@app.route("/admin/vaccine-requests/<request_id>/status", methods=["POST"])
def update_request_status(request_id):
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    new_status = request.form.get("status")
    db.vaccineRequests.update_one({"_id": ObjectId(request_id)}, {"$set": {"status": new_status, "updated_at": datetime.utcnow()}})
    db.auditLogs.insert_one({
        "action": "request_status_update",
        "request_id": request_id,
        "status": new_status,
        "created_at": datetime.utcnow(),
    })
    flash("Request status updated.", "success")
    return redirect(url_for("admin_requests"))


@app.route("/admin/transfers")
def admin_transfers():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    transfers = list(db.transfers.find({}).sort("created_at", -1))
    for transfer in transfers:
        supplier = db.facilities.find_one({"_id": ObjectId(transfer["supplier_facility_id"])})
        recipient = db.facilities.find_one({"_id": ObjectId(transfer["recipient_facility_id"])})
        vaccine = db.vaccines.find_one({"_id": ObjectId(transfer["vaccine_id"])})
        transfer["supplier_name"] = supplier["facility_name"] if supplier else "Unknown"
        transfer["recipient_name"] = recipient["facility_name"] if recipient else "Unknown"
        transfer["vaccine_name"] = vaccine["name"] if vaccine else "Unknown"
    return render_template(
        "admin_transfers.html",
        transfers=transfers,
        facilities=list(db.facilities.find({}).sort("facility_name", 1)),
        vaccines=list(db.vaccines.find({"status": "active"}).sort("name", 1)),
    )


@app.route("/admin/transfers/new", methods=["POST"]) 
def create_transfer():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    supplier_id = request.form.get("supplier_facility_id")
    recipient_id = request.form.get("recipient_facility_id")
    vaccine_id = request.form.get("vaccine_id")
    qty = int(request.form.get("quantity") or 0)
    batch = request.form.get("batch_number", "")

    if supplier_id and recipient_id and vaccine_id and qty > 0:
        record = {
            "supplier_facility_id": supplier_id,
            "recipient_facility_id": recipient_id,
            "vaccine_id": vaccine_id,
            "quantity": qty,
            "batch_number": batch,
            "status": "Pending Dispatch",
            "created_at": datetime.utcnow(),
        }
        db.transfers.insert_one(record)
        db.notifications.insert_one({
            "title": "Transfer scheduled",
            "message": "A new vaccine transfer has been created.",
            "type": "transfer",
            "created_at": datetime.utcnow(),
        })
        flash("Transfer created successfully.", "success")
    else:
        flash("Please complete all transfer details.", "error")
    return redirect(url_for("admin_transfers"))


@app.route("/admin/messages")
def admin_messages():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    messages = list(db.messages.find({}).sort("created_at", -1))
    for msg in messages:
        facility = db.facilities.find_one({"_id": ObjectId(msg["facility_id"])}) if msg.get("facility_id") else None
        msg["facility_name"] = facility["facility_name"] if facility else "Unknown"
    return render_template(
        "admin_messages.html",
        messages=messages,
        facilities=list(db.facilities.find({}).sort("facility_name", 1)),
    )


@app.route("/admin/messages/reply", methods=["POST"]) 
def admin_reply_message():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    facility_id = request.form.get("facility_id")
    text = request.form.get("message", "").strip()
    if facility_id and text:
        db.messages.insert_one({
            "facility_id": facility_id,
            "sender": "ministry_admin",
            "content": text,
            "created_at": datetime.utcnow(),
            "direction": "reply",
        })
        flash("Reply sent to facility.", "success")
    return redirect(url_for("admin_messages"))


@app.route("/admin/reports")
def admin_reports():
    user = current_user()
    if not user or user.get("role") != "ministry_admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    usage = list(db.stockTransactions.find({"type": "usage"}).sort("date", -1).limit(10))
    shortages = list(db.vaccineRequests.find({"status": {"$in": ["Pending", "Under Review", "Approved"]}}))
    return render_template("admin_reports.html", usage=usage, shortages=shortages)


@app.route("/hospital/dashboard")
def hospital_dashboard():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    facility = facility_from_user(user)
    if not facility:
        flash("No facility assigned to this account.", "error")
        return redirect(url_for("login"))

    inventory = list(db.inventory.find({"facility_id": str(facility["_id"]), "$or": [{"is_active": {"$exists": False}}, {"is_active": True}]}))
    total_vaccine_types = len({entry["vaccine_id"] for entry in inventory})
    total_available_doses = sum(int(entry.get("quantity_available", 0)) for entry in inventory)
    low_stock = sum(1 for entry in inventory if 0 < int(entry.get("quantity_available", 0)) <= int(entry.get("minimum_stock", 0)))
    out_of_stock = sum(1 for entry in inventory if int(entry.get("quantity_available", 0)) == 0)
    incoming_transfers = db.transfers.count_documents({"recipient_facility_id": str(facility["_id"])})
    recent = list(db.stockTransactions.find({"facility_id": str(facility["_id"])}).sort("date", -1).limit(5))
    stats = {
        "total_vaccine_types": total_vaccine_types,
        "total_available_doses": total_available_doses,
        "low_stock": low_stock,
        "out_of_stock": out_of_stock,
        "incoming_transfers": incoming_transfers,
        "recent_activities": recent,
    }
    return render_template("hospital_dashboard.html", facility=facility, stats=stats)


@app.route("/hospital/inventory")
def hospital_inventory():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    inventory = list(db.inventory.find({"facility_id": str(facility["_id"]), "$or": [{"is_active": {"$exists": False}}, {"is_active": True}]}))
    rows = []
    for item in inventory:
        vaccine = db.vaccines.find_one({"_id": ObjectId(item["vaccine_id"])})
        rows.append({
            "_id": item.get("_id"),
            "vaccine_id": item.get("vaccine_id"),
            "vaccine_name": vaccine["name"] if vaccine else "Unknown",
            "manufacturer": vaccine.get("manufacturer", "") if vaccine else "",
            "batch_number": item.get("batch_number", ""),
            "quantity_available": int(item.get("quantity_available", 0)),
            "expiry_date": item.get("expiry_date", ""),
            "minimum_stock": item.get("minimum_stock", 0),
            "status": "Low Stock" if 0 < int(item.get("quantity_available", 0)) <= int(item.get("minimum_stock", 0)) else "Out of Stock" if int(item.get("quantity_available", 0)) == 0 else "Available",
        })
    return render_template("hospital_inventory.html", rows=rows, facility=facility, vaccines=list(db.vaccines.find({"status": "active"}).sort("name", 1)))


@app.route("/hospital/inventory/add", methods=["GET", "POST"]) 
def hospital_inventory_add():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    if request.method == "POST":
        vaccine_id = request.form.get("vaccine_id")
        quantity = int(request.form.get("quantity_received") or 0)
        batch_number = request.form.get("batch_number", "").strip()
        expiry_date = request.form.get("expiry_date")
        if not vaccine_id or quantity <= 0 or not batch_number:
            flash("Please provide a vaccine, batch number and quantity.", "error")
            return render_template("hospital_inventory_add.html", vaccines=list(db.vaccines.find({"status": "active"}).sort("name", 1)), facility=facility)

        db.inventory.insert_one({
            "facility_id": str(facility["_id"]),
            "vaccine_id": vaccine_id,
            "manufacturer": request.form.get("manufacturer", "").strip(),
            "batch_number": batch_number,
            "quantity_available": quantity,
            "expiry_date": expiry_date,
            "minimum_stock": int(request.form.get("minimum_stock", 0) or 0),
            "date_received": request.form.get("date_received") or datetime.utcnow().date().isoformat(),
            "supplier": request.form.get("supplier", "").strip(),
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        db.stockTransactions.insert_one({
            "facility_id": str(facility["_id"]),
            "vaccine_id": vaccine_id,
            "type": "stock_received",
            "batch_number": batch_number,
            "quantity": quantity,
            "date": request.form.get("date_received") or datetime.utcnow().date().isoformat(),
            "created_at": datetime.utcnow(),
        })
        flash("Inventory batch added successfully.", "success")
        return redirect(url_for("hospital_inventory"))

    return render_template("hospital_inventory_add.html", vaccines=list(db.vaccines.find({"status": "active"}).sort("name", 1)), facility=facility)


@app.route("/hospital/inventory/<inventory_id>/edit", methods=["GET", "POST"]) 
def hospital_inventory_edit(inventory_id):
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    item = db.inventory.find_one({"_id": ObjectId(inventory_id), "facility_id": str(facility["_id"])})
    if not item:
        flash("Inventory entry not found.", "error")
        return redirect(url_for("hospital_inventory"))

    if request.method == "POST":
        vaccine_id = request.form.get("vaccine_id")
        quantity = int(request.form.get("quantity_available") or 0)
        batch_number = request.form.get("batch_number", "").strip()
        if not vaccine_id or quantity < 0 or not batch_number:
            flash("Please provide a valid vaccine, quantity and batch number.", "error")
            return render_template("hospital_inventory_edit.html", item=item, vaccines=list(db.vaccines.find({"status": "active"}).sort("name", 1)), facility=facility)

        db.inventory.update_one({"_id": ObjectId(inventory_id)}, {"$set": {
            "vaccine_id": vaccine_id,
            "manufacturer": request.form.get("manufacturer", "").strip(),
            "batch_number": batch_number,
            "quantity_available": quantity,
            "expiry_date": request.form.get("expiry_date"),
            "minimum_stock": int(request.form.get("minimum_stock", 0) or 0),
            "supplier": request.form.get("supplier", "").strip(),
            "updated_at": datetime.utcnow(),
        }})
        flash("Inventory batch updated successfully.", "success")
        return redirect(url_for("hospital_inventory"))

    return render_template("hospital_inventory_edit.html", item=item, vaccines=list(db.vaccines.find({"status": "active"}).sort("name", 1)), facility=facility)


@app.route("/hospital/inventory/<inventory_id>/delete", methods=["POST"]) 
def hospital_inventory_delete(inventory_id):
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    db.inventory.update_one({"_id": ObjectId(inventory_id), "facility_id": str(facility["_id"])}, {"$set": {"is_active": False, "updated_at": datetime.utcnow()}})
    flash("Inventory batch archived successfully.", "success")
    return redirect(url_for("hospital_inventory"))


@app.route("/hospital/register-stock", methods=["GET", "POST"]) 
def hospital_register_stock():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    if request.method == "POST":
        vaccine_id = request.form.get("vaccine_id")
        quantity = int(request.form.get("quantity_received") or 0)
        batch_number = request.form.get("batch_number", "").strip()
        expiry_date = request.form.get("expiry_date")
        if not vaccine_id or quantity <= 0:
            flash("Please provide a vaccine and quantity.", "error")
            return render_template("hospital_stock_form.html", vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)

        entry = db.inventory.find_one({"facility_id": str(facility["_id"]), "vaccine_id": vaccine_id, "batch_number": batch_number, "$or": [{"is_active": {"$exists": False}}, {"is_active": True}]})
        if entry is None:
            db.inventory.insert_one({
                "facility_id": str(facility["_id"]),
                "vaccine_id": vaccine_id,
                "manufacturer": request.form.get("manufacturer", "").strip(),
                "batch_number": batch_number,
                "quantity_available": quantity,
                "expiry_date": expiry_date,
                "minimum_stock": int(request.form.get("minimum_stock", 0) or 0),
                "date_received": request.form.get("date_received"),
                "supplier": request.form.get("supplier", "").strip(),
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })
        else:
            new_qty = int(entry.get("quantity_available", 0)) + quantity
            db.inventory.update_one({"_id": entry["_id"]}, {"$set": {"quantity_available": new_qty, "expiry_date": expiry_date, "updated_at": datetime.utcnow()}})
        db.stockTransactions.insert_one({
            "facility_id": str(facility["_id"]),
            "vaccine_id": vaccine_id,
            "type": "stock_received",
            "batch_number": batch_number,
            "quantity": quantity,
            "date": request.form.get("date_received") or datetime.utcnow().date().isoformat(),
            "created_at": datetime.utcnow(),
        })
        db.auditLogs.insert_one({
            "action": "register_stock",
            "facility_id": str(facility["_id"]),
            "vaccine_id": vaccine_id,
            "quantity": quantity,
            "created_at": datetime.utcnow(),
        })
        flash("New stock registered successfully.", "success")
        return redirect(url_for("hospital_inventory"))

    return render_template("hospital_stock_form.html", vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)


@app.route("/hospital/usage", methods=["GET", "POST"]) 
def hospital_usage():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    if request.method == "POST":
        vaccine_id = request.form.get("vaccine_id")
        batch_number = request.form.get("batch_number", "").strip()
        quantity = int(request.form.get("quantity_administered") or 0)
        if not vaccine_id or quantity <= 0:
            flash("Please provide valid usage details.", "error")
            return render_template("hospital_usage.html", vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)

        entry = db.inventory.find_one({"facility_id": str(facility["_id"]), "vaccine_id": vaccine_id, "batch_number": batch_number, "$or": [{"is_active": {"$exists": False}}, {"is_active": True}]})
        if not entry:
            flash("No matching batch found for this vaccine.", "error")
            return render_template("hospital_usage.html", vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)
        available = int(entry.get("quantity_available", 0))
        if quantity > available:
            flash("Usage exceeds available stock for this batch.", "error")
            return render_template("hospital_usage.html", vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)

        remaining = available - quantity
        db.inventory.update_one({"_id": entry["_id"]}, {"$set": {"quantity_available": remaining, "updated_at": datetime.utcnow()}})
        db.stockTransactions.insert_one({
            "facility_id": str(facility["_id"]),
            "vaccine_id": vaccine_id,
            "batch_number": batch_number,
            "type": "usage",
            "quantity": quantity,
            "date": request.form.get("date_administered") or datetime.utcnow().date().isoformat(),
            "staff_member": request.form.get("staff_member", "").strip(),
            "created_at": datetime.utcnow(),
        })
        db.auditLogs.insert_one({
            "action": "record_usage",
            "facility_id": str(facility["_id"]),
            "vaccine_id": vaccine_id,
            "quantity": quantity,
            "created_at": datetime.utcnow(),
        })
        flash("Vaccine usage recorded and inventory updated.", "success")
        return redirect(url_for("hospital_inventory"))

    return render_template("hospital_usage.html", vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)


@app.route("/hospital/requests", methods=["GET", "POST"]) 
def hospital_requests():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    if request.method == "POST":
        vaccine_id = request.form.get("vaccine_id")
        quantity = int(request.form.get("quantity_requested") or 0)
        reason = request.form.get("reason", "").strip()
        urgency = request.form.get("urgency", "Normal")
        if vaccine_id and quantity > 0:
            db.vaccineRequests.insert_one({
                "facility_id": str(facility["_id"]),
                "vaccine_id": vaccine_id,
                "quantity_requested": quantity,
                "reason": reason,
                "urgency": urgency,
                "status": "Pending",
                "date_submitted": datetime.utcnow(),
                "created_at": datetime.utcnow(),
            })
            db.notifications.insert_one({
                "title": "Vaccine request submitted",
                "message": f"{facility['facility_name']} submitted a vaccine request.",
                "type": "vaccine_request",
                "created_at": datetime.utcnow(),
            })
            flash("Your vaccine request was submitted.", "success")
            return redirect(url_for("hospital_requests"))
        flash("Please enter a valid vaccine request.", "error")

    requests = list(db.vaccineRequests.find({"facility_id": str(facility["_id"])}).sort("created_at", -1))
    for req in requests:
        vaccine = db.vaccines.find_one({"_id": ObjectId(req["vaccine_id"])})
        req["vaccine_name"] = vaccine["name"] if vaccine else "Unknown"
    return render_template("hospital_requests.html", requests=requests, vaccines=list(db.vaccines.find({"status": "active"})), facility=facility)


@app.route("/hospital/transfers")
def hospital_transfers():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    transfers = list(db.transfers.find({"recipient_facility_id": str(facility["_id"])}).sort("created_at", -1))
    for transfer in transfers:
        source = db.facilities.find_one({"_id": ObjectId(transfer["supplier_facility_id"])})
        vaccine = db.vaccines.find_one({"_id": ObjectId(transfer["vaccine_id"])})
        transfer["supplier_name"] = source["facility_name"] if source else "Unknown"
        transfer["vaccine_name"] = vaccine["name"] if vaccine else "Unknown"
    return render_template("hospital_transfers.html", transfers=transfers, facility=facility)


@app.route("/hospital/transfers/<transfer_id>/confirm-receipt", methods=["POST"]) 
def confirm_transfer_receipt(transfer_id):
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    transfer = db.transfers.find_one({"_id": ObjectId(transfer_id)})
    if transfer and transfer.get("recipient_facility_id") == str(facility["_id"]):
        db.transfers.update_one({"_id": ObjectId(transfer_id)}, {"$set": {"status": "Received", "receipt_confirmed_at": datetime.utcnow()}})
        db.inventory.insert_one({
            "facility_id": str(facility["_id"]),
            "vaccine_id": transfer["vaccine_id"],
            "batch_number": transfer.get("batch_number", ""),
            "quantity_available": transfer["quantity"],
            "minimum_stock": 0,
            "expiry_date": "",
            "created_at": datetime.utcnow(),
        })
        flash("Transfer receipt confirmed and stock added to inventory.", "success")
    else:
        flash("This transfer cannot be confirmed by your facility.", "error")
    return redirect(url_for("hospital_transfers"))


@app.route("/hospital/messages", methods=["GET", "POST"]) 
def hospital_messages():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    if request.method == "POST":
        content = request.form.get("message", "").strip()
        if content:
            db.messages.insert_one({
                "facility_id": str(facility["_id"]),
                "sender": "facility",
                "content": content,
                "created_at": datetime.utcnow(),
                "direction": "outbound",
            })
            flash("Message sent to Ministry Admin.", "success")
    messages = list(db.messages.find({"facility_id": str(facility["_id"])}).sort("created_at", -1))
    return render_template("hospital_messages.html", messages=messages, facility=facility)


@app.route("/hospital/profile")
def hospital_profile():
    user = current_user()
    if not user or user.get("role") != "hospital":
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    facility = facility_from_user(user)
    return render_template("hospital_profile.html", facility=facility)


@app.route("/admin/seed")
def seed_demo_data():
    ensure_seed_data()
    return "Seed complete" 


if __name__ == "__main__":
    from waitress import serve

    print("Serving DRC Vaccine supply chain on http://127.0.0.1:5000")
    serve(app, host="0.0.0.0", port=5000)
