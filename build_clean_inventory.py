"""
One-time script: builds inventory_clean.xlsx in the project root.
Run:  python build_clean_inventory.py

Produces one sheet per lab area with clean headers on row 1.
Import the resulting file via the app's Import page.
"""

import pandas as pd

HEADERS = ["Item Description", "Category", "Quantity", "Unit", "Capacity", "Location", "Remarks"]


def row(name, cat, qty, unit, cap="", loc="", rem=""):
    return [name, cat, qty, unit, cap, loc, rem]


data = {}

# -----------------------------------------------------------------------------
# Biochemical Analysis
# -----------------------------------------------------------------------------
data["Biochemical Analysis"] = [
    row("Laboratory bottle", "Glassware", 6, "pcs", "2000 mL"),
    row("Laboratory bottle", "Glassware", 6, "pcs", "1000 mL"),
    row("Volumetric flask", "Glassware", 5, "pcs", "1000 mL"),
    row("Pipette", "Pipettes", 2, "pcs", "2–200 µL"),
    row("Pipette", "Pipettes", 1, "pcs", "5–50 µL"),
    row("Pipette", "Pipettes", 1, "pcs", "0.5–10 µL"),
    row("Pipette", "Pipettes", 2, "pcs", "100–1000 µL"),
    row("Pipette", "Pipettes", 2, "pcs", "10–100 µL"),
    row("Pipette", "Pipettes", 1, "pcs", "2–20 µL"),
    row("Measuring cylinder", "Glassware", 1, "pcs", "1000 mL"),
    row("Pipette stand", "Accessories", 2, "pcs"),
    row("Conical flask", "Glassware", 5, "pcs", "2000 mL"),
    row("Bottle", "Glassware", 4, "pcs", "100 mL"),
    row("Bottle", "Glassware", 5, "pcs", "500 mL"),
    row("Bottle", "Glassware", 2, "pcs", "250 mL"),
    row("Measuring cylinder", "Glassware", 4, "pcs", "100 mL"),
    row("Volumetric flask", "Glassware", 2, "pcs", "100 mL"),
    row("Volumetric flask", "Glassware", 2, "pcs", "50 mL"),
    row("Water bath shake", "Equipment", 1, "pcs"),
    row("Spectrophotometer", "Equipment", 2, "pcs"),
    row("Measuring cylinder", "Glassware", 1, "pcs", "300 mL"),
    row("Measuring cylinder", "Glassware", 1, "pcs", "250 mL"),
    row("Inoculating loop", "Microbiology equipment", 1, "pcs"),
    row("Wash brush", "Cleaning materials", 6, "pcs"),
    row("Vortex", "Equipment", 1, "pcs"),
    row("Blender", "Equipment", 1, "pcs"),
    row("Filter funnel", "Glassware", 4, "pcs"),
    row("Volumetric flask", "Glassware", 2, "pcs", "10 mL"),
    row("Orbital shaker", "Equipment", 2, "pcs"),
    row("Electronic balance", "Equipment", 1, "pcs"),
    row("Microscope", "Equipment", 1, "pcs"),
]

# -----------------------------------------------------------------------------
# Microbio 2
# -----------------------------------------------------------------------------
data["Microbio 2"] = [
    row("Biobase Centrifuge", "Equipment", 3, "pcs"),
    row("Digital Centrifuge", "Equipment", 1, "pcs"),
    row("Microscope", "Equipment", 1, "pcs"),
    row("Incubator", "Equipment", 1, "pcs"),
    row("Vortex Mixer", "Equipment", 1, "pcs"),
    row("Refrigerated Centrifuge", "Equipment", 1, "pcs"),
    row("Filter", "Equipment", 1, "pcs"),
]

# -----------------------------------------------------------------------------
# Preparation Lab
# -----------------------------------------------------------------------------
data["Preparation Lab"] = [
    row("500 ml bottle", "Glassware", 46, "pcs"),
    row("1000 ml bottle", "Glassware", 3, "pcs"),
    row("25 ml bottle", "Glassware", 15, "pcs"),
    row("10-100 μl pipette", "Pipettes", 1, "pcs"),
    row("0.5-10 μl pipette", "Pipettes", 1, "pcs"),
    row("2-20 μl pipette", "Pipettes", 1, "pcs"),
    row("100 ml bottle", "Glassware", 16, "pcs"),
    row("50 ml bottle", "Glassware", 8, "pcs"),
    row("Tripod stand", "Equipment", 3, "pcs"),
    row("200 ml bottle", "Glassware", 3, "pcs"),
    row("Pipette pumps", "Pipettes", 5, "pcs"),
    row("2000 ml bottle", "Glassware", 2, "pcs"),
    row("250 ml bottle", "Glassware", 1, "pcs"),
    row("250 ml measuring cylinder", "Glassware", 1, "pcs"),
    row("1000 ml measuring cylinder", "Glassware", 1, "pcs"),
    row("1000 ml conical flask", "Glassware", 3, "pcs"),
    row("500 ml conical flask", "Glassware", 4, "pcs"),
    row("50 ml volumetric flask", "Glassware", 1, "pcs"),
    row("100 ml volumetric flask", "Glassware", 3, "pcs"),
    row("10 ml volumetric flask", "Glassware", 3, "pcs"),
    row("250 ml volumetric flask", "Glassware", 1, "pcs"),
    row("Ion / pH meter", "Equipment", 1, "pcs"),
    row("Magnetic stirrer", "Equipment", 1, "pcs"),
    row("Pipette stand", "Equipment", 1, "pcs"),
    row("Bunsen burner", "Equipment", 3, "pcs"),
    row("Wash brush", "Cleaning material", 43, "pcs"),
    row("Water distiller", "Equipment", 1, "pcs"),
    row("Test tube holder", "Equipment", 1, "pcs"),
]

# -----------------------------------------------------------------------------
# Preparation Room
# -----------------------------------------------------------------------------
data["Preparation Room"] = [
    row("Methanol AR", "Chemical", 2.5, "L"),
    row("HCL 32%", "Chemical", 5, "L"),
    row("Glucose Powder", "Chemical", 10, "box"),
    row("Protective gowns", "PPE", 2, "set"),
    row("Hydrogen Peroxide (20 volume)", "Chemical", 2.5, "L"),
    row("Gallic acid", "Chemical", 1, "bottle"),
    row("Isolation gown", "PPE", 1, "set"),
    row("Phenol Reagent", "Chemical", 500, "mL"),
    row("Vanillin", "Chemical", 1, "bottle"),
    row("Acetone AR", "Chemical", 2.5, "L"),
    row("Chloroform", "Chemical", 2.5, "L"),
]

# -----------------------------------------------------------------------------
# Microbiology Lab Equipment
# -----------------------------------------------------------------------------
data["Microbiology Lab Equipment"] = [
    row("Bunsen burners", "Equipment", 3, "pcs"),
    row("Tripod stand", "Equipment", 3, "pcs"),
    row("2000ml bottles", "Glassware", 2, "pcs"),
    row("250ml measuring cylinder", "Glassware", 1, "pcs"),
    row("Weighing balance", "Equipment", 1, "pcs"),
    row("Centrifuge", "Equipment", 1, "pcs"),
    row("Autoclave", "Equipment", 1, "pcs"),
]

# -----------------------------------------------------------------------------
# Microbiology Lab
# -----------------------------------------------------------------------------
data["Microbiology Lab"] = [
    row("Multiscope Tissue", "Consumable", 2, "roll"),
    row("Disposable mask", "PPE", 1, "box"),
    row("Slides", "Glassware", 4, "box"),
    row("Formalin", "Chemical", 5, "L"),
    row("Ethanol", "Chemical", 20, "L"),
    row("Lysine Iron Agar", "Media", 500, "g"),
    row("Monkey Broth Purple", "Media", 500, "g"),
    row("Latex Gloves", "PPE", 0, "box", "", "", "Quantity unknown at source"),
    row("Sabouraud Dextrose Agar", "Media", 500, "g"),
    row("Nutrient Agar", "Media", 500, "g"),
    row("Soyabean Casein Digest Medium", "Media", 500, "g"),
    row("Blood Agar No.2", "Media", 500, "g"),
    row("Blood Agar Base (Infusion Agar)", "Media", 500, "g"),
    row("Parafin film", "Consumable", 1, "roll"),
    row("Biohazard box", "Consumable", 7, "pcs"),
    row("Giemsa stain solution", "Stain", 500, "mL"),
    row("Eosin stain solution", "Stain", 1, "L"),
    row("Petri Dishes", "Plasticware", 918, "pcs"),
    row("Cotton", "Consumable", 1, "pack"),
    row("Filter paper", "Consumable", 0, "pcs", "", "", "Quantity unknown at source"),
]

# -----------------------------------------------------------------------------
# Write the workbook
# -----------------------------------------------------------------------------
output_file = "inventory_clean.xlsx"

with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
    for sheet_name, rows in data.items():
        df = pd.DataFrame(rows, columns=HEADERS)
        df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

print(f"Wrote {output_file}")
print(f"Sheets: {list(data.keys())}")
print(f"Total items: {sum(len(v) for v in data.values())}")