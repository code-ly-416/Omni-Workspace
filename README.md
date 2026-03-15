# Omni Workspace
#### Video Demo: https://www.youtube.com/watch?v=mAHnIuMi5Pc
#### Description:

This is my final project for CS50x. I call it Omni Workspace. It is a productivity web app built with Python, Flask, and SQLite.

The main idea behind this project was to keep everything in one place: tasks, projects, courses, categories, and tags. As a student, I realized I was spending more time organizing my assignments and goals across different apps than actually doing them. I wanted to build something that felt simple and clean to use, but was still flexible enough for real day-to-day planning.

Normally, basic to-do lists are just flat—you write a task, you check it off, and it's gone. I wanted to build an app where tasks actually belong to a bigger picture.

### How the App is Organized

I designed the app to have a specific structure so things stay organized:
* **Categories & Courses:** These are the base level. Categories are broad things like "Health" or "Academics" (and you can pick custom colors for them). Courses are specifically for tracking university classes.
* **Projects:** These are the actual goals. You link a project to a Category and a Course.
* **Tasks & Routines:** This is where the actual work happens. Every task can be linked to a project, given a priority (High, Medium, Low), an energy requirement, and a due date.
* **Tags:** Because sometimes tasks need to share context across different projects, I added a tagging system. You can attach multiple tags to a single task using a many-to-many relationship in the database.

### The Tech Stack and Database

Under the hood, the app runs on Python and Flask. For the frontend, I used HTML, CSS, JavaScript, and Bootstrap 5. I focused a lot on making the UI clean, responsive, and practical. Instead of using default Bootstrap, I wrote a lot of custom CSS to give it a modern, minimal look with soft shadows and no harsh borders.

For the database, I originally thought about using Microsoft SQL Server, but I realized that was way too heavy and complicated for a local app. I switched to SQLite3, which keeps everything simple in one `omniworkspace.db` file.

The database has 7 tables: `users`, `categories`, `courses`, `projects`, `tasks`, `tags`, and `task_tags`. Even though I am using SQLAlchemy, I decided to just use it to manage the connection and write raw SQL queries (using `text()`). This gave me full control over how the data is joined, especially for the complex dashboard calendar.

### Cool Features I Built

There are a few technical things I am really proud of in this project:

**1. The Routine Engine:** I didn't just want tasks; I wanted recurring habits. I wrote custom Python logic so that when you complete a "Routine," the app checks if the interval is daily, weekly, or monthly. It then automatically calculates the next due date and clones a fresh version of the task into the database, keeping the old one marked as completed.

**2. Live Filtering:** On the Tasks and Projects pages, I wanted users to be able to find things quickly. Instead of making the server reload the page every time you search or click a filter dropdown, I wrote vanilla JavaScript to handle it client-side. As you type or click checkboxes, it instantly hides or shows rows in the table.

**3. The Dashboard:** The main page pulls everything together. It shows active project cards, a list of tasks due specifically today, and an interactive calendar that plots out your entire workload.

### Future Improvements

The app works great right now, but I have some plans for the future. I want to add keyboard shortcuts (like Ctrl+Z to undo actions) by keeping track of the state history on the client side. I also want to build a better analytics dashboard to track productivity over time, and eventually, integrate an AI feature that can automatically turn a typed sentence into a fully formatted task.

### Files in this Project

* `app.py`: The main Python file handling all the Flask routes and SQL queries.
* `schema.sql`: Contains all the table structures and relationships for the database.
* `requirements.txt`: Lists all the Python packages required to run the server.
* `static/styles.css`: All the custom styling and UI tweaks.
* `static/js/`: To keep the frontend architecture clean, I split my client-side logic into dedicated, modular JavaScript files (`app-shell.js`, `dashboard.js`, `tasks.js`, `projects.js`, and `courses.js`) rather than stuffing everything into the HTML.
* `templates/`: This folder holds all the HTML files. `layout.html` is the base template, and the others handle the dashboard, tasks, projects, etc.

### How to Run This Project

To use the app from scratch, you can literally just delete the `.db` file (if exists) and it automatically recreates it using the schema.

1. Set up a Python virtual environment: `python -m venv venv`
2. Activate it (e.g., `venv\Scripts\activate` on Windows).
3. Install the required packages: `pip install -r requirements.txt`
4. Start the server: `python app.py`.
5. Open your browser to `http://127.0.0.1:5000` to register an account and start using the app.
