# Five-minute assessment walkthrough

Use the fictional patient in `voice/sample-patient.json`. Never expose tokens in the recording.

1. Show the dashboard and explain: voice capture plus an authenticated patient API, with a persistent database.
2. Start a voice call. Give first/last name and city together to show out-of-order collection. Give the remaining required details naturally.
3. Correct the phone number before saving. Decline email/insurance or give the fictional optional values; they are optional, not blockers.
4. Listen for the **complete** readback, including corrected data and every collected optional field. Say “no, change the city” once, then ensure another full readback happens.
5. Say “yes, please save.” The assistant should say success only after the tool commits. Refresh the dashboard and inspect the new patient.
6. Search by last name, update a field from the staff form, and inspect the UUID and UTC timestamps.
7. Show automated tests and final synthetic JSON from the smoke script/logs. Restart the app and retrieve the same UUID to demonstrate persistence. Optionally soft-delete the fictional record and show it no longer appears.

Second short scenario: start over before review, provide an invalid future DOB, or decline to save. No patient should be created.

What to explain if asked:
- Shared validation prevents dashboard and voice rules drifting
- Review tokens are invalidated by corrections; transcript checks require a new affirmative
- A patient and saved-call receipt commit together; retries do not duplicate the patient
- SQLite file persistence needs a retained disk; hosted PostgreSQL is recommended
- This is an assessment demo, with clear production security/compliance work remaining
