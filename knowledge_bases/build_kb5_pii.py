"""Populate KB-5 with synthetic PII examples (Faker-generated), used by L8's output
guard as a semantic backstop behind the SECRET_PATTERNS regex scan. For a real thesis
deployment, replace/extend these with your actual PII taxonomy categories, each tagged
with pii_category, regex_pattern, and example_phrases[] as in the KB-5 schema."""
from faker import Faker

from knowledge_bases.kb_manager import kb

fake = Faker()
Faker.seed(42)

EXAMPLES_PER_CATEGORY = 200

PII_GENERATORS = {
    "ssn": lambda: f"My social security number is {fake.ssn()}",
    "credit_card": lambda: f"My credit card number is {fake.credit_card_number()}",
    "email": lambda: f"You can reach me at {fake.email()}",
    "phone": lambda: f"Call me at {fake.phone_number()}",
    "address": lambda: f"I live at {fake.address()}",
    "full_name": lambda: f"My full name is {fake.name()}",
    "date_of_birth": lambda: f"I was born on {fake.date_of_birth()}",
    "bank_account": lambda: f"My bank account number is {fake.iban()}",
}


def build():
    documents, metadatas, ids = [], [], []
    for category, generator in PII_GENERATORS.items():
        for i in range(EXAMPLES_PER_CATEGORY):
            documents.append(generator())
            metadatas.append({"pii_category": category, "source": "faker_synthetic"})
            ids.append(f"pii_{category}_{i}")

    embeddings = kb.embed(documents)
    for i in range(0, len(documents), 4000):
        kb.kb5_pii.add(
            documents=documents[i:i + 4000], embeddings=embeddings[i:i + 4000],
            ids=ids[i:i + 4000], metadatas=metadatas[i:i + 4000],
        )
    print(f"KB-5 populated with {len(documents)} synthetic PII examples across {len(PII_GENERATORS)} categories.")


if __name__ == "__main__":
    build()
