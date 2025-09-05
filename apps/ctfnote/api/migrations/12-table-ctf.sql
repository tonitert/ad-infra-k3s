CREATE TABLE ctfnote.ctf (
  "id" serial PRIMARY KEY NOT NULL,
  "title" text NOT NULL,
  CHECK ("title" <> ''),
  "weight" float NOT NULL default 0,
  "ctf_url" text,
  "logo_url" text,
  "ctftime_url" text,
  "description" text NOT NULL DEFAULT '',
  "start_time" timestamptz NOT NULL,
  "end_time" timestamptz NOT NULL,
  "secrets_id" int NOT NULL REFERENCES ctfnote.ctf_secrets (id) ON DELETE CASCADE
);

CREATE INDEX ON ctfnote.ctf (secrets_id);

CREATE INDEX ON ctfnote.ctf (end_time);

CREATE INDEX ON ctfnote.ctf (start_time);

GRANT SELECT ON TABLE ctfnote.ctf TO user_guest;

GRANT INSERT (title, weight, ctf_url, logo_url, ctftime_url, description, start_time, end_time) ON ctfnote.ctf TO user_manager;

GRANT UPDATE (title, weight, ctf_url, logo_url, ctftime_url, description, start_time, end_time) ON ctfnote.ctf TO user_manager;

GRANT DELETE ON ctfnote.ctf TO user_manager;

GRANT usage ON SEQUENCE ctfnote.ctf_id_seq
  TO user_manager;


/* create a ctf-secrets entry when a ctf is created */
CREATE FUNCTION ctfnote_private.create_ctf_secrets ()
  RETURNS TRIGGER
  AS $$
DECLARE
  secrets_id int;
BEGIN
  INSERT INTO ctfnote.ctf_secrets (credentials)
    VALUES ('')
  RETURNING
    id INTO secrets_id;
  NEW.secrets_id := secrets_id;
  RETURN NEW;
END
$$
SECURITY DEFINER
LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION ctfnote_private.create_ctf_secrets TO user_manager;

CREATE TRIGGER on_create_ctf
  BEFORE INSERT ON ctfnote.ctf
  FOR EACH ROW
  EXECUTE PROCEDURE ctfnote_private.create_ctf_secrets ();

