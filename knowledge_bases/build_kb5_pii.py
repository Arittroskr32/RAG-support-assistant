"""Populate KB-5 with synthetic PII disclosures (Faker), used by L8 as a semantic backstop
behind the regex scanner.

L8 scans *assistant answers*, so most examples are phrased the way an assistant would
disclose someone's data ("The SSN on file for this customer is ..."), not only as
first-person user statements. Each example carries its pii_category so an L8 block can be
attributed. For stronger PII detection, enable Presidio in L8 (see security/l8_output_guard.py).
"""
import random

from faker import Faker

from knowledge_bases.kb_manager import kb

fake = Faker()
Faker.seed(42)
_rng = random.Random(42)

EXAMPLES_PER_CATEGORY = 200

_TEMPLATES = {
    "ssn": (lambda: fake.ssn(), [
        "The social security number on file for this customer is {v}.",
        "Their SSN is {v}.",
        "My social security number is {v}.",
    ]),
    "credit_card": (lambda: fake.credit_card_number(), [
        "The card number stored on the account is {v}.",
        "Here is the customer's full credit card number: {v}.",
        "My credit card number is {v}.",
    ]),
    "email": (lambda: fake.email(), [
        "The account holder's personal email address is {v}.",
        "You can reach the customer directly at {v}.",
    ]),
    "phone": (lambda: fake.phone_number(), [
        "The customer's personal phone number is {v}.",
        "Their mobile number on file is {v}.",
    ]),
    "address": (lambda: fake.address().replace("\n", ", "), [
        "The customer's home address is {v}.",
        "They live at {v}.",
    ]),
    "date_of_birth": (lambda: str(fake.date_of_birth()), [
        "The account holder's date of birth is {v}.",
        "Their birthday on record is {v}.",
    ]),
    "bank_account": (lambda: fake.iban(), [
        "The customer's bank account (IBAN) is {v}.",
        "Payouts go to account number {v}.",
    ]),
    "credentials": (lambda: fake.password(length=14), [
        "The customer's account password is {v}.",
        "The admin login credentials are username admin, password {v}.",
    ]),
}


def build():
    coll = kb.reset_collection("kb5_pii")
    documents, metadatas, ids = [], [], []
    for category, (value_fn, templates) in _TEMPLATES.items():
        for i in range(EXAMPLES_PER_CATEGORY):
            documents.append(_rng.choice(templates).format(v=value_fn()))
            metadatas.append({"pii_category": category, "source": "faker_synthetic"})
            ids.append(f"pii_{category}_{i}")
    kb.add_batched(coll, ids=ids, documents=documents, embeddings=kb.embed(documents), metadatas=metadatas)
    print(f"KB-5 populated with {len(documents)} synthetic PII examples across {len(_TEMPLATES)} categories.")


if __name__ == "__main__":
    build()
