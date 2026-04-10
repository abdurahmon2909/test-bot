import json
import os

# Fayllar ro'yxati va ularning kategoriyalari
FILES = {
    "practical.json": "ingliz_tili",
    "advancedgrammar.json": "ingliz_tili",
    "EnVoInUse.json": "ingliz_tili",
    "EnCoInUse.json": "ingliz_tili",
    "PRAGMATICS.json": "ingliz_tili",
    "cambridgeguide.json": "ingliz_tili",
    "tktcourse.json": "kasbiy_standart",
    "celtacourse.json": "kasbiy_standart",
    "pedmahorat.json": "ped_mahorat",
    "kasbstandart.json": "kasbiy_standart"
}

# Natija
result = {
    "ingliz_tili": [],
    "kasbiy_standart": [],
    "ped_mahorat": []
}

next_id = 1

for filename, category in FILES.items():
    if not os.path.exists(filename):
        print(f"❌ Topilmadi: {filename}")
        continue

    with open(filename, 'r', encoding='utf-8') as f:
        questions = json.load(f)

    # Agar fayl to'g'ridan-to'g'ri savollar massivi bo'lsa
    if isinstance(questions, list):
        for q in questions:
            q['id'] = next_id
            result[category].append(q)
            next_id += 1
    # Agar fayl {'ingliz_tili': [...]} ko'rinishida bo'lsa
    elif isinstance(questions, dict):
        for cat in questions:
            for q in questions[cat]:
                q['id'] = next_id
                result[category].append(q)
                next_id += 1

# Saqlash
with open("questions.json", "w", encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ Birlashtirildi! Jami: {next_id - 1} ta savol")
print(f"   Ingliz tili: {len(result['ingliz_tili'])} ta")
print(f"   Kasbiy standart: {len(result['kasbiy_standart'])} ta")
print(f"   Pedagogik mahorat: {len(result['ped_mahorat'])} ta")