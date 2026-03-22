import sqlite3
import csv

conn = sqlite3.connect("database.db")
c = conn.cursor()

# Clear old data
c.execute("DELETE FROM mcq")

current_module = None
with open("questions.csv", newline='', encoding='utf-8') as file:
    reader = csv.reader(file)
    header = next(reader)
    # header expected: semester,subject,question,option1,option2,option3,option4,answer
    for row in reader:
        if not row:
            continue
        first = row[0].strip()
        # detect module header lines that start with '#'
        if first.startswith('#'):
            # capture module text after '#'
            current_module = ','.join(row).lstrip('#').strip()
            continue

        # normal data rows - ensure we have at least 8 columns
        if len(row) < 8:
            continue

        semester = row[0].strip()
        subject = row[1].strip()
        question = row[2].strip()
        option1 = row[3].strip()
        option2 = row[4].strip()
        option3 = row[5].strip()
        option4 = row[6].strip()
        answer = row[7].strip()

        c.execute("""
        INSERT INTO mcq (semester,subject,question,option1,option2,option3,option4,answer,module)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            semester,
            subject,
            question,
            option1,
            option2,
            option3,
            option4,
            answer,
            current_module
        ))

conn.commit()
conn.close()

print("All MCQs imported successfully!")
