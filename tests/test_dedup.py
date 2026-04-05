"""Quick test for duplicate detection improvements."""

import sys
from pathlib import Path

from services import tools

# Ensure we can import from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import db

db.init_databases()

print("=== Title Similarity Tests ===")
pairs = [
    ("Bootloader", "Bootloader in Embedded Systems"),
    ("Bootloader", "Embedded Bootloaders"),
    ("Bootloader in Embedded Systems", "Embedded Bootloaders"),
    ("304 vs 316 Stainless Steel", "Covariance"),
    ("ESP-IDF Memory Regions", "ISR Best Practices"),
]
for a, b in pairs:
    sim = db._title_similarity(a, b)
    flag = " *** DUPLICATE" if sim >= 0.5 else ""
    print(f"  {sim:.2f}  {a!r} vs {b!r}{flag}")

print("\n=== Maintenance Duplicate Detection ===")
d = db.get_maintenance_diagnostics()
dupes = d["potential_duplicates"]
print(f"Found {len(dupes)} potential duplicate(s):")
for p in dupes:
    a, b = p["concept_a"], p["concept_b"]
    print(f'  #{a["id"]} "{a["title"]}" <-> #{b["id"]} "{b["title"]}"')

print("\n=== Add Concept Guard Test ===")

msg_type, result = tools._handle_add_concept(
    {"title": "Embedded Bootloader", "topic_titles": ["Embedded Systems"]}
)
print(f"  {msg_type}: {result}")

print("\nDone.")
