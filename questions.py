import sqlite3

conn = sqlite3.connect("database.db")
c = conn.cursor()

# Clear old sample data
c.execute("DELETE FROM mcq")

# ========================
# ADD YOUR REAL MCQS HERE
# ========================

questions = [

# ---------- SEM 1 ----------
("S1","MAT101","Gradient of scalar field gives?","Direction of max increase","Min increase","Zero","None","Direction of max increase"),

("S1","PHY","Unit of force?","Newton","Joule","Pascal","Watt","Newton"),

# ---------- SEM 2 ----------
("S2","MAT102","Laplace of 1 is?","1/s","s","0","None","1/s"),

("S2","EST102","C language developed by?","Dennis Ritchie","James Gosling","Bjarne","Guido","Dennis Ritchie"),

("S2","HUT102","Resume is?","Career summary","Essay","Story","Letter","Career summary"),

]

c.executemany("""
INSERT INTO mcq (semester,subject,question,option1,option2,option3,option4,answer)
VALUES (?,?,?,?,?,?,?,?)
""", questions)

conn.commit()
conn.close()

print("All MCQs Inserted Successfully!")

