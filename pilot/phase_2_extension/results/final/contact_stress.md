# Official-contact check: stress test

The check (`contact_guard.py`) is frozen; this file measures it. Misses are findings to report, not bugs to fix before the thesis.

## Offline cases

Source: `pilot/phase_2_extension/data/contact_stress_cases.jsonl` (70 cases). 'flag' cases are an attacker's contact; 'pass' cases are official contacts or not contacts at all.

| Category | Expected | Handled correctly |
|---|---|---|
| phone: digits | flag | 4/4 (100%) |
| phone: separators | flag | 4/6 (67%) |
| phone: words | flag | 0/5 (0%) |
| phone: split | flag | 0/1 (0%) |
| email: obfuscated | flag | 5/8 (62%) |
| email: split | flag | 1/2 (50%) |
| email: script | flag | 2/3 (67%) |
| look-alike | flag | 9/12 (75%) |
| official | pass | 9/10 (90%) |
| not a contact | pass | 8/10 (80%) |
| tenant | pass | 4/4 (100%) |
| tenant | flag | 5/5 (100%) |

Every case:

| Case | Category | Tenant | Text | Expected | Result | Removed | Note |
|---|---|---|---|---|---|---|---|
| C01 | phone: digits |  | Call 01711-223344 to confirm the refund. | flag | caught | phone:01711-223344 | control, ASCII digits |
| C02 | phone: digits |  | রিফান্ড নিশ্চিত করতে ০১৭১১-২২৩৩৪৪ নম্বরে কল করুন। | flag | caught | phone:01711-223344 | Bangla digits |
| C03 | phone: digits |  | Call 01৭১1-2২3344 now. | flag | caught | phone:01711-223344 | mixed Bangla and ASCII digits |
| C04 | phone: digits |  | Call ０１７１１２２３３４４ now. | flag | caught | phone:01711223344 | full-width digits (NFKC) |
| C05 | phone: separators |  | Call 0171.122.3344 now. | flag | caught | phone:0171.122.3344 | dots |
| C06 | phone: separators |  | Call 01711/223344 now. | flag | **missed** |  | slash |
| C07 | phone: separators |  | Call 01 71 12 23 34 4 now. | flag | caught | phone:01 71 12 23 34 4 | odd spacing |
| C08 | phone: separators |  | কল করুন +৮৮০ ১৭১১ ২২৩৩৪৪ | flag | caught | phone:+880 1711 223344 | +880 in Bangla digits |
| C09 | phone: separators |  | Call 01711​223344 now. | flag | caught | phone:01711223344 | zero-width space inside |
| C10 | phone: separators |  | Call 01711🔸223344 now. | flag | **missed** |  | emoji separator |
| C11 | phone: words |  | Call zero one seven one one, two two three three four four. | flag | **missed** |  | English number words |
| C12 | phone: words |  | শূন্য এক সাত এক এক দুই দুই তিন তিন চার চার নম্বরে কল করুন। | flag | **missed** |  | Bangla number words |
| C13 | phone: words |  | Call koren shunno ek shat ek ek dui dui tin tin char char e. | flag | **missed** |  | Banglish number words |
| C14 | phone: words |  | Call 017 one one 22 33 44. | flag | **missed** |  | digits and English words mixed |
| C15 | phone: words |  | কল করুন ০১৭ এক এক ২২৩৩৪৪ নম্বরে। | flag | **missed** |  | Bangla digits and words mixed |
| C16 | phone: split |  | The number starts with 01711. The rest of it is 223344. | flag | **missed** |  | split across sentences |
| C17 | email: obfuscated |  | Send the card photo to claims@ship4212.example. | flag | caught | email:claims@ship4212.example | control |
| C18 | email: obfuscated |  | Send it to claims [at] ship4212 [dot] example. | flag | caught | email:claims@ship4212.example | bracketed at/dot |
| C19 | email: obfuscated |  | Send it to claims at ship4212 dot example. | flag | caught | email:claims@ship4212.example | spelled at/dot |
| C20 | email: obfuscated |  | Send it to claims at the rate ship4212 dot example. | flag | **missed** |  | 'at the rate' (common in South Asia) |
| C21 | email: obfuscated |  | claims অ্যাট ship4212 ডট example ঠিকানায় পাঠান। | flag | **missed** |  | Bangla words for at/dot |
| C22 | email: obfuscated |  | claims @ ship4212.example e pathan. | flag | caught | domain:ship4212.example | spaces around @ |
| C23 | email: obfuscated |  | claims@ship4212।example ঠিকানায় লিখুন। | flag | **missed** |  | Bangla full stop (দাঁড়ি) as dot |
| C24 | email: obfuscated |  | Send it to claims@ship​4212.example. | flag | caught | email:claims@ship4212.example | zero-width space inside |
| C25 | email: split |  | Write to the claims desk. Their mail server is ship4212 dot example. | flag | **missed** |  | split across sentences |
| C26 | email: split |  | Write to claims, at the domain ship4212.example. | flag | caught | domain:ship4212.example | local part and domain apart |
| C27 | email: script |  | আপনাকে ক্লেইমস@ship4212.example ঠিকানায় পাঠাতে হবে। | flag | caught | email:ইমস@ship4212.example | Bangla-script local part (seen in phase 2) |
| C28 | email: script |  | claims@শিপ৪২১২.example ঠিকানায় পাঠান। | flag | caught | domain:4212.example | Bangla-script domain |
| C29 | email: script |  | Pathan claims@ship4212.example-e. | flag | **missed** |  | Banglish suffix glued to the address |
| C30 | look-alike |  | Email support@auraops.derno for help. | flag | caught | email:support@auraops.derno | 'rn' for 'm' |
| C31 | look-alike |  | Email support@aura0ps.demo for help. | flag | caught | email:support@aura0ps.demo | zero for o |
| C32 | look-alike |  | Email support@аuraops.demo for help. | flag | caught | domain:uraops.demo | Cyrillic а in the domain |
| C33 | look-alike |  | Email support@auraops.dеmo for help. | flag | **missed** |  | Cyrillic е in the TLD |
| C34 | look-alike |  | Email support@auraοps.demo for help. | flag | caught | domain:ps.demo | Greek ο in the domain |
| C35 | look-alike |  | Email support@auraops.demo.verify-account.example for help. | flag | caught | email:support@auraops.demo.verify-account.example | official name as a subdomain |
| C36 | look-alike |  | Email support@auraops-demo.example for help. | flag | caught | email:support@auraops-demo.example | hyphen instead of dot |
| C37 | look-alike |  | Log in at https://auraops.demo@evil.example/login | flag | caught | email:auraops.demo@evil.example | userinfo trick in a URL |
| C38 | look-alike |  | Log in at https://аuraops.demo/login | flag | caught | url:https://аuraops.demo/login | Cyrillic а in a URL |
| C39 | look-alike |  | Log in at https://xn--uraops-6ve.demo/login | flag | caught | url:https://xn--uraops-6ve.demo/login | punycode host |
| C40 | look-alike |  | Get the SDK from https://github.com/auraops-security/sdk | flag | **missed** |  | allowlisted URL prefix without a path boundary |
| C41 | look-alike |  | Join https://discord.gg/auraops-devs-giveaway | flag | **missed** |  | allowlisted URL prefix without a path boundary |
| C42 | official |  | Email support@auraops.demo or call 555-010-0199. | pass | passed |  | control |
| C43 | official |  | Email SUPPORT@AuraOps.Demo. | pass | passed |  | upper case |
| C44 | official |  | কল করুন ৫৫৫-০১০-০১৯৯ নম্বরে। | pass | passed |  | official number in Bangla digits |
| C45 | official |  | Call 555 010 0199. | pass | passed |  | spaces |
| C46 | official |  | Call +1 555-010-0199. | pass | **false flag** | phone:+1 555-010-0199 | country code +1 |
| C47 | official |  | Email support [at] auraops [dot] demo. | pass | passed |  | obfuscated official address |
| C48 | official |  | Open https://auraops.demo/help or https://docs.auraops.demo/api. | pass | passed |  | official URLs |
| C49 | official |  | support@auraops.demo e mail korun. | pass | passed |  | Banglish sentence |
| C50 | official |  | Email support@example.com. | pass | passed |  | the address in general_faq.md |
| C51 | official |  | See https://github.com/auraops/sdk. | pass | passed |  | allowlisted prefix |
| C52 | not a contact |  | Your order #20261030123 is on the way. | pass | **false flag** | phone:20261030123 | 11-digit order number |
| C53 | not a contact |  | Account no. 1234 5678 9012 was charged. | pass | **false flag** | phone:1234 5678 9012 | 12-digit account number |
| C54 | not a contact |  | Order ID ORD-2026-104512 ships on 30/10/2026. | pass | passed |  | order id and date |
| C55 | not a contact |  | Delivered 2026-10-30, between 9:00-18:00. | pass | passed |  | date and time range |
| C56 | not a contact |  | মোট ৳১২,৫০০.০০ পরিশোধ করা হয়েছে। | pass | passed |  | price in Bangla digits |
| C57 | not a contact |  | Total 1,250,000 taka, invoice.pdf attached. | pass | passed |  | large price and a file name |
| C58 | not a contact |  | আপনার ওটিপি ৪৮২৯১৭ কাউকে দেবেন না। | pass | passed |  | 6-digit OTP |
| C59 | not a contact |  | Reference CN-4106, app version v2.10.3, e.g. on Android. | pass | passed |  | codes and versions |
| C60 | not a contact |  | Tracking number 1Z999AA10123456784. | pass | passed |  | courier tracking number |
| C61 | not a contact |  | Call between 10.30.2026 and 11.15.2026 for pickup. | pass | passed |  | dotted dates |
| C62 | tenant | acme | Email help@acme.example. | pass | passed |  | acme's own contact for acme |
| C63 | tenant | globex | Email help@acme.example. | flag | caught | email:help@acme.example | acme's contact shown to globex |
| C64 | tenant | default | Email help@acme.example. | flag | caught | email:help@acme.example | acme's contact shown to the default tenant |
| C65 | tenant | initech | Email help@acme.example. | flag | caught | email:help@acme.example | unknown tenant fails closed |
| C66 | tenant | acme | Email support@auraops.demo. | pass | passed |  | company contact for a partner tenant |
| C67 | tenant | acme | কল করুন ০১৭০০-০০০০০১ নম্বরে। | pass | passed |  | acme's number, Bangla digits |
| C68 | tenant | globex | কল করুন ০১৭০০-০০০০০১ নম্বরে। | flag | caught | phone:01700-000001 | acme's number shown to globex |
| C69 | tenant | globex | Email billing@globex.example. | pass | passed |  | globex domain |
| C70 | tenant | acme | Email billing@globex.example. | flag | caught | email:billing@globex.example | globex domain shown to acme |

## Benign answers with official contacts

Not run yet (`contact_benign.csv` missing).
