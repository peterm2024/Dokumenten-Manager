"""Thunderbird-Testprofil ohne echte Mails für tests/test_mail_quellen.py, nach dem dokumentierten Aufbau (Spike S5)."""
import email.utils
import os
import shutil


def mail(nr, betreff, status="0001", status2="00000000", text="Guten Tag.", von="Musterversand <info@musterversand.example>"):
    datum = email.utils.format_datetime(email.utils.parsedate_to_datetime(f"Fri, {1 + nr % 28:02d} Mar 2024 10:00:00 +0100"))
    return (f"From - Fri Mar {1 + nr % 28:02d} 10:00:00 2024\n"
            f"X-Mozilla-Status: {status}\nX-Mozilla-Status2: {status2}\n"
            f"From: {von}\nTo: Max Mustermann <max@beispiel.example>\nSubject: {betreff}\nDate: {datum}\n"
            f"Message-ID: <s5-{nr}@musterversand.example>\nContent-Type: text/plain; charset=utf-8\n\n{text}\n\n")


def schreibe(pfad, inhalt):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write(inhalt)


def mbox(ordner, name, *mails, msf=b"// <!-- <mdb:mork:z v=\"1.4\"/> -->"):
    """mbox-Datei samt .msf-Index, wie Thunderbird sie je Ordner anlegt."""
    schreibe(os.path.join(ordner, name), "".join(mails))
    with open(os.path.join(ordner, name + ".msf"), "wb") as f:
        f.write(msf)


PREFS = """// Mozilla User Preferences
user_pref("mail.accountmanager.accounts", "account1,account2,account3,account4,account5");
user_pref("mail.account.account1.server", "server1");
user_pref("mail.account.account1.identities", "id1");
user_pref("mail.account.account2.server", "server2");
user_pref("mail.account.account2.identities", "id2,id3");
user_pref("mail.account.account3.server", "server3");
user_pref("mail.account.account4.server", "server4");
user_pref("mail.account.account5.server", "server5");
user_pref("mail.identity.id1.useremail", "max@beispiel.example");
user_pref("mail.identity.id2.useremail", "max.mustermann@firma.example");
user_pref("mail.identity.id3.useremail", "MAX@firma.example");
user_pref("mail.server.server1.type", "pop3");
user_pref("mail.server.server1.name", "Konto Beispiel");
user_pref("mail.server.server1.directory-rel", "[ProfD]Mail/pop.beispiel.example");
user_pref("mail.server.server2.type", "imap");
user_pref("mail.server.server2.name", "Konto Firma");
user_pref("mail.server.server2.directory-rel", "[ProfD]ImapMail/imap.firma.example");
user_pref("mail.server.server3.type", "none");
user_pref("mail.server.server3.name", "Lokale Ordner");
user_pref("mail.server.server3.directory-rel", "[ProfD]Mail/Local Folders");
user_pref("mail.server.server4.type", "rss");
user_pref("mail.server.server4.name", "Blogs");
user_pref("mail.server.server4.directory-rel", "[ProfD]Mail/Feeds");
user_pref("mail.server.server5.type", "pop3");
user_pref("mail.server.server5.name", "Konto verschoben");
user_pref("mail.server.server5.directory", "%VERSCHOBEN%");
"""


def baue(ziel):
    shutil.rmtree(ziel, ignore_errors=True)
    tb = os.path.join(ziel, "AppData", "Roaming", "Thunderbird")
    p1 = os.path.join(tb, "Profiles", "abcd1234.default-release")
    p2 = os.path.join(ziel, "AndererOrt", "zweites-profil")

    schreibe(os.path.join(tb, "profiles.ini"), (
        "[Install308046B0AF4A39CB]\nDefault=Profiles/abcd1234.default-release\nLocked=1\n\n"
        "[Profile0]\nName=default-release\nIsRelative=1\nPath=Profiles/abcd1234.default-release\n\n"
        f"[Profile1]\nName=zweites\nIsRelative=0\nPath={p2}\n\n"
        "[Profile2]\nName=geloeschtes\nIsRelative=1\nPath=Profiles/gibt-es-nicht\n\n"
        "[General]\nStartWithLastProfile=1\nVersion=2\n"))

    verschoben = os.path.join(ziel, "D_Mails", "verschobenes Konto")
    schreibe(os.path.join(p1, "prefs.js"), PREFS.replace("%VERSCHOBEN%", verschoben.replace("\\", "\\\\")))

    # Dateien mit Zugangsdaten und Beiwerk: dürfen nie kopiert werden
    for name in ("logins.json", "key4.db", "cert9.db", "cookies.sqlite", "abook.sqlite", "global-messages-db.sqlite"):
        schreibe(os.path.join(p1, name), "GEHEIM")

    # POP: Inbox mit Gelöschter, gekürzter Mail und den beiden „From“-Fällen im Text
    pop = os.path.join(p1, "Mail", "pop.beispiel.example")
    mbox(pop, "Inbox",
         mail(1, "Normale Rechnung"),
         mail(2, "Gelöscht, noch nicht komprimiert", status="0009"),
         mail(3, "Nur teilweise geladen", status="0401"),
         mail(4, "Text mit maskiertem From", text="Erste Zeile\n\n>From Hamburg nach Berlin\nLetzte Zeile"),
         mail(5, "Text mit unmaskiertem From", text="Erste Zeile\n\nFrom Hamburg nach Berlin\nLetzte Zeile"))
    mbox(pop, "Sent", mail(6, "Gesendete Mail", von="Max Mustermann <max@beispiel.example>"))
    mbox(pop, "Trash", mail(7, "Im Papierkorb"))
    mbox(pop, "Junk", mail(8, "Spam"))
    mbox(pop, "Drafts", mail(21, "Nie abgeschickter Entwurf", von="Max Mustermann <max@beispiel.example>"))
    mbox(pop, "Templates", mail(22, "Vorlage Kündigung", von="Max Mustermann <max@beispiel.example>"))
    mbox(os.path.join(pop, "Archives.sbd"), "2024", mail(9, "Archiv 2024"))
    mbox(os.path.join(pop, "Archives.sbd", "2024.sbd"), "März.Belege", mail(10, "Unterordner mit Punkt im Namen"))
    for name, inhalt in (("msgFilterRules.dat", "version=\"9\""), ("popstate.dat", "x"), ("filterlog.html", "<html>")):
        schreibe(os.path.join(pop, name), inhalt)

    # IMAP: offline vorgehaltene Mails; ein Ordner nur mit dem Index, der Text liegt allein auf dem Server
    imap = os.path.join(p1, "ImapMail", "imap.firma.example")
    mbox(imap, "INBOX",
         mail(11, "IMAP offline", status="0081"),
         mail(12, "Auf dem Server gelöscht", status="0081", status2="00200000"))
    mbox(os.path.join(imap, "INBOX.sbd"), "Nur-Online", msf=b"// mork " + b"x" * 200_000)
    # Lokale Ordner, Feeds, verschobenes Konto
    lokal = os.path.join(p1, "Mail", "Local Folders")
    mbox(lokal, "Unsent Messages")
    mbox(os.path.join(lokal, "Steuer.sbd"), "2023", mail(13, "Lokaler Ordner"))
    mbox(os.path.join(p1, "Mail", "Feeds"), "Nachrichten", mail(14, "Feed, keine Mail"))
    mbox(verschoben, "Inbox", mail(15, "Konto an anderem Ort"))

    # Zweites Profil, Konto im Maildir-Format (seltene Thunderbird-Einstellung)
    schreibe(os.path.join(p2, "prefs.js"), "\n".join([
        'user_pref("mail.accountmanager.accounts", "account1");',
        'user_pref("mail.account.account1.server", "server1");',
        'user_pref("mail.server.server1.type", "pop3");',
        'user_pref("mail.server.server1.directory-rel", "[ProfD]Mail/pop.maildir.example");',
        'user_pref("mail.server.server1.storeContractID", "@mozilla.org/msgstore/maildirstore;1");', ""]))
    schreibe(os.path.join(p2, "Mail", "pop.maildir.example", "Inbox", "cur", "1700000000.M1"), mail(16, "Maildir"))
    return tb
