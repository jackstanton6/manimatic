#!/usr/bin/env python3
"""Generate the demo exam paper (needs reportlab): python tools/make_demo_exam.py out.pdf"""
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def main(out: str) -> None:
    c = canvas.Canvas(out, pagesize=A4)
    _, H = A4
    y = H - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, y, "Mathematics Examination 2023")
    y -= 40
    c.setFont("Helvetica", 11)

    def line(t, dy=18, x=60):
        nonlocal y
        c.drawString(x, y, t)
        y -= dy

    for q in range(1, 6):
        if y < 200:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = H - 60
        line(f"Question {q} (6 marks)", 22)
        if q == 4:
            line("Let f(x) = x^2 + 1 for all real x.", 20, 75)
            line("(a) Find f(3).", 20, 75)
            line("(b) Show that f(x) is never prime for even x > 2.", 18, 75)
            line("     Use the diagram below.", 14, 75)
            c.circle(200, y - 40, 35)
            y -= 95
            line("(c) Sketch the graph of y = f(x).", 30, 75)
        else:
            line(f"Prove that the sum of the first {q} odd numbers is {q}^2.", 18, 75)
            line("Show all working.", 30, 75)
    c.save()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "exam2023.pdf")
