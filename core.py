"Core functions"
import gi
gi.require_version('GnomeDesktop', '3.0')
from gi.repository import GLib, Gio, GnomeDesktop
import os
import json
import tempfile
import logging
logging.basicConfig(level=logging.INFO)
import copy
import mimetypes
import sqlite3
from multiprocessing import Pool, TimeoutError
import hashlib
import itertools
import numpy as np
import base64
import random
from PIL import Image
import face_recognition

class WontOverwriteError(Exception): pass

def get_data_file():
    folder = os.path.join(GLib.get_user_cache_dir(), "photo-face-tagger")
    filepath = os.path.join(folder, "faces.db")
    try:
        os.makedirs(folder)
    except FileExistsError:
        pass
    return filepath

def get_db():
    conn = sqlite3.connect(get_data_file())
    return conn

def init(overwrite=False):
    dbf = get_data_file()
    if os.path.exists(dbf) and not overwrite:
        raise WontOverwriteError("There already is a data file; remove it.")
    if os.path.exists(dbf):
        os.unlink(dbf)
    db = get_db()
    c = db.cursor()
    c.execute("""CREATE TABLE images (id integer primary key, 
        full_path text, filename text, md5 text, thumbnail text, 
        facecount int, width int, height int)""")
    c.execute("""CREATE UNIQUE INDEX idx_full_path ON images (full_path)""")
    c.execute("""CREATE TABLE faces (id integer primary key, 
        image int, x int, y int, w int, h int, encoding text)""")
    c.execute("""CREATE TABLE pairs (face1 int, face2 int, distance real, grouped int)""")
    c.execute("""CREATE UNIQUE INDEX idx_pairs ON pairs (face1, face2)""")
    c.execute("""CREATE TABLE groups (id integer primary key, name text, best_face int)""")
    c.execute("""CREATE TABLE faces2groups (face int, groupid int)""")
    db.commit()

def load_from_folder(folder):
    db = get_db()
    c = db.cursor()
    count = 0
    for dirpath, dirname, filenames in os.walk(folder):
        images = [x for x in filenames if x.lower().endswith(".jpg") or x.lower().endswith(".png")]
        full_images = [{
            "id": None,
            "full_path": os.path.abspath(os.path.join(dirpath, f)), 
            "filename": f,
            "md5": None,
            "thumbnail": None,
            "facecount": None
        } for f in images]
        if full_images:
            c.executemany("""INSERT OR IGNORE INTO images 
                (id, full_path, filename, md5, thumbnail, facecount) VALUES 
                (:id, :full_path, :filename, :md5, :thumbnail, :facecount)""", full_images)
            count += len(full_images)
    db.commit()
    return count

def create_thumbnail(file_path):
    "Guaranteed to return a valid image url; if it can't make a thumbnail it returns the original"
    tf = GnomeDesktop.DesktopThumbnailFactory.new(GnomeDesktop.DesktopThumbnailSize.NORMAL)
    logging.debug("Creating new thumbnail for %s", file_path)
    main_image_url = GLib.filename_to_uri(file_path)
    mimetype, encoding = mimetypes.guess_type(file_path)
    thumbnail_pixbuf = tf.generate_thumbnail(main_image_url, mimetype)
    if thumbnail_pixbuf:
        mtime = os.path.getmtime(file_path)
        tf.save_thumbnail(thumbnail_pixbuf, main_image_url, mtime)
        image_url = tf.lookup(main_image_url, mtime)
        logging.debug("Created new thumbnail for %s", file_path)
        return image_url, True
    logging.debug("Failed to generate thumbnail for %s so returning original", file_path)
    return main_image_url, False

def get_md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def load_single(image):
    image_id, full_path = image
    frim = face_recognition.load_image_file(full_path)
    locations = face_recognition.face_locations(frim)
    encodings = face_recognition.face_encodings(frim, known_face_locations=locations)
    md5 = get_md5(full_path)
    thumbnail, success = create_thumbnail(full_path)
    im = Image.open(full_path)
    return (image_id, locations, encodings, md5, thumbnail, im.size[0], im.size[1])

def analyse_images_in_blocks():
    # Get the next N images that need processing, and process them
    # Use multiprocessing because it's faster
    db = get_db()
    c = db.cursor()
    pool = Pool() # don't use all processors, or the machine hangs
    chunk_size = 24 # higher is better, but we might run out of memory
    c.execute("select count(*) from images where md5 is null")
    cnt = c.fetchone()[0]
    if cnt == 0: return (0, 0) # none left to process
    c.execute("select id, full_path from images where md5 is null limit ?", (chunk_size,))
    images = c.fetchall()
    results = pool.map(load_single, images) # map can take a chunksize, but we don't want all results in one huge object
    pool.close()
    pool.join()

    image_updates = []
    face_inserts = []
    for image_id, locations, encodings, md5, thumbnail, width, height in results:
        image_updates.append({"id": image_id, "md5": md5, 
            "thumbnail": thumbnail, "facecount": len(encodings), "width": width, "height": height})
        if encodings:
            for loc, enc in zip(locations, encodings):
                face_inserts.append({
                    "id": None,
                    "image": image_id,
                    "encoding": base64.a85encode(enc.tostring()),
                    "x": loc[3],
                    "y": loc[0],
                    "w": loc[1] - loc[3],
                    "h": loc[2] - loc[0]
                })
    c.executemany("""update images set md5=:md5, thumbnail=:thumbnail, facecount=:facecount,
                    width=:width, height=:height where id=:id""", image_updates)
    c.executemany("""INSERT OR IGNORE INTO faces 
        (id, image, x, y, w, h, encoding)
        VALUES (:id, :image, :x, :y, :w, :h, :encoding)""", face_inserts)
    db.commit()
    return len(image_updates), cnt - len(image_updates)

def insert_empty_pairs():
    db = get_db()
    c = db.cursor()
    c.execute("select id from faces")
    face_ids = [x[0] for x in c.fetchall()]
    pairs = ({"face1": x[0], "face2": x[1], "distance": None} 
        for x in itertools.combinations(face_ids, 2))
    c.executemany("""INSERT OR IGNORE INTO pairs 
        (face1, face2, distance, grouped)
        VALUES (:face1, :face2, :distance, 0)""", pairs)
    db.commit()

def pair_faces_in_blocks():
    db = get_db()
    c = db.cursor()
    c.execute("select count(*) from pairs where distance is null")
    cnt = c.fetchone()[0]
    if cnt == 0: return (0,0)
    chunk_size = 500
    c.execute("""select p.face1, p.face2, f1.encoding, f2.encoding
                        from pairs p inner join faces f1 on p.face1 = f1.id
                        inner join faces f2 on p.face2 = f2.id
                        where distance is null limit ?""", (chunk_size,))
    pairs_updates = []
    while True:
        nxt = c.fetchone()
        if not nxt: break
        face1, face2, encoding_string1, encoding_string2 = nxt
        encoding1 = np.fromstring(base64.a85decode(encoding_string1))
        encoding2 = np.fromstring(base64.a85decode(encoding_string2))
        distance = np.linalg.norm(encoding1 - encoding2)
        pairs_updates.append({"face1": face1, "face2": face2, "distance": distance})
    c.executemany("UPDATE pairs SET distance=:distance WHERE face1=:face1 AND face2=:face2", pairs_updates)
    db.commit()
    return len(pairs_updates), cnt

def random_name(length=7):
    if length % 2 == 0: length += 1 # odd only so we begin and end w/ consonant
    start_consonants = list("bdfghjklmnprstvwz")
    mid_consonants = list("bdfgklmnprstvwxz")
    end_consonants = list("dfgklmnprstx")
    vowels = list("aeiou")
    word = [random.choice(start_consonants)]
    for i in range((length-3)//2):
        word.append(random.choice(vowels))
        word.append(random.choice(mid_consonants))
    word.append(random.choice(vowels))
    word.append(random.choice(end_consonants))
    return "".join(word)

def group_faces_in_blocks(distance=0.5):
    db = get_db()
    c = db.cursor()
    chunk_size = 10
    c.execute("""select count(*) from pairs where distance <= ? and grouped=0""", (distance,))
    cnt = c.fetchone()[0]
    if cnt == 0: return (0,0)
    c.execute("""select face1, face2 from pairs where distance <= ? and grouped=0 limit ?""", (distance, chunk_size,))
    pairs = c.fetchall()
    for face1, face2 in pairs:
        c.execute("select face, groupid from faces2groups where face = ? or face = ?", (face1,face2))
        f2g = c.fetchall()
        groups = list(set([x[1] for x in f2g]))
        if len(groups) > 1:
            # these two images match, and are in more than one group; combine those groups
            qmarks = ["?"] * (len(groups) - 1)
            qmarks_str = ",".join(qmarks)
            sql = "update faces2groups set groupid=? where groupid in ({})".format(qmarks_str)
            c.execute(sql, groups)
            sql = "delete from groups where id in ({})".format(qmarks_str);
            c.execute(sql, groups[1:])
        elif len(groups) == 1 and len(f2g) == 2:
            # Already in same group; nothing to do
            pass
        elif len(groups) == 1:
            if f2g[0][0] == face1:
                # Add f2 to f1's group
                c.execute("insert into faces2groups (face, groupid) values (?,?)", (face2, groups[0]))
            elif f2g[0][0] == face2:
                # Add f1 to f2's group
                c.execute("insert into faces2groups (face, groupid) values (?,?)", (face1, groups[0]))
            else:
                # shouldn't happen
                pass
        else:
            # create a new group and put f1 and f2 in it
            c.execute("insert into groups (name) values (null)")
            groupid = c.lastrowid
            c.execute("insert into faces2groups (face, groupid) values (?,?)", (face1, groupid))
            c.execute("insert into faces2groups (face, groupid) values (?,?)", (face2, groupid))
        c.execute("update pairs set grouped=1 where face1=? and face2=?", (face1, face2))
        db.commit()
    return len(pairs), cnt

def find_best_faces():
    db = get_db()
    c = db.cursor()
    sql = """select g.id, f.id, max(100 * f.w * f.h / i.width / i.height) from images i
        inner join faces f on f.image = i.id inner join faces2groups f2g on f.id = f2g.face
        inner join groups g on f2g.groupid = g.id group by g.id"""
    c.execute(sql)
    updates = [{"id": x[0], "face": x[1]} for x in c.fetchall()]
    c.executemany("UPDATE groups set best_face = :face where id = :id", updates)
    db.commit()

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_groups_and_faces():
    db = get_db()
    c = db.cursor()
    sql = """select g.id, g.name, f.x, f.y, f.w, f.h, i.full_path
        from groups g inner join faces f on g.best_face = f.id
        inner join images i on f.image = i.id"""
    c.execute(sql)
    out = [dict(zip(["groupid", "groupname", "x", "y", "w", "h", "image"], r)) for r in c.fetchall()]
    return out

def update_groupname(groupid, name):
    db = get_db()
    c = db.cursor()
    c.execute("update groups set name = ? where id = ?", (name, groupid))
    db.commit()

def simple_gallery(output):
    db = get_db()
    c = db.cursor()
    c.execute("""select g.id, g.name, i.thumbnail, i.filename, i.full_path, f.x, f.y, f.w, f.h, i.width, i.height
        from groups g inner join faces2groups f2g on g.id = f2g.groupid
        inner join faces f on f2g.face = f.id
        inner join images i on f.image = i.id
        order by g.name, i.filename
        """)
    groups = {}
    for groupid, groupname, thumbnail, filename, full_path, fx, fy, fw, fh, iw, ih in c.fetchall():
        gn = groupname if groupname else "Group {}".format(groupid)
        if gn not in groups: groups[gn] = []
        groups[gn].append((thumbnail, filename, full_path, fx, fy, fw, fh, iw, ih))
    with open(output, encoding="utf-8", mode="w") as fp:
        fp.write("""<!doctype html>
            <html><head><meta charset="utf-8"><title>Autogrouped gallery</title>
            <style>
            body { font-family: sans-serif; color: white; background: #444444; padding-top: 50px; }
            figure { float: left; margin: 4px; position: relative; overflow: hidden; }
            img { max-height: 150px; box-shadow: 2px 2px 2px rgba(0,0,0,0.6); }
            h1 { clear: both; font-size: 16px; font-weight: bold; }
            div { display: flex; flex-flow: wrap row; }
            figure span { outline: 2000px solid rgba(0,0,0,0.6);
                border: 1px solid rgba(255,255,255,0.4);
                display: none; position: absolute; }
            body.show-faces figure span { display: block; }
            p { position: fixed; top: 0; left: 0; width: 100%; margin: 0; z-index: 3;
                background: #444444; box-shadow: 0 3px 3px rgba(0,0,0,0.5); padding: 1em; }
            figure.bigfig {
                position: fixed;
                top: 50%;
                left: 50%;
                width: 800px;
                height: 600px;
                border: 2000px solid rgba(0,0,0,0.5);
                transform: translateX(-50%) translateY(-50%);
                box-sizing: content-box;
            }
            figure.bigfig img {
                max-width: 100%;
                max-height: 100%;
            }
            </style>
            </head><body><p><label><input type="checkbox"> Show faces</label></p>
            """)
        for groupname in groups:
            fp.write("\n<h1>{}</h1><div>".format(groupname))
            for thumbnail, filename, full_path, fx, fy, fw, fh, iw, ih in sorted(groups[groupname], key=lambda x:x[1]):
                fxpc = 100 * float(fx) / iw
                fypc = 100 * float(fy) / ih
                fwpc = 100 * float(fw) / iw
                fhpc = 100 * float(fh) / ih
                fp.write("""<figure>
                    <img src="{}" data-face="{},{},{},{}" data-full="{}">
                    </figure>""".format(thumbnail, fxpc, fypc, fwpc, fhpc, full_path))
            fp.write("</div>")
        fp.write("""<script>
            var madeFaces = false;
            document.querySelector("input").onchange = function() {
                if (this.checked) {
                    if (!madeFaces) {
                        Array.from(document.querySelectorAll("img")).forEach(function(img) {
                            fpc = img.dataset.face.split(",").map(v => { return parseFloat(v); })
                            var span = document.createElement("span");
                            var fig = img.parentNode;
                            var scaley = img.offsetHeight / fig.offsetHeight;
                            span.style.top = (fpc[1] * scaley) + "%";
                            span.style.height = (fpc[3] * scaley) + "%";
                            span.style.left = fpc[0] + "%";
                            span.style.width = fpc[2] + "%";
                            fig.appendChild(span);
                        })
                        madeFaces = true;
                    }
                    document.body.className = "show-faces";
                } else {
                    document.body.className = "";
                }
            }
            document.body.onclick = function(e) {
                if (e.target.nodeName.toLowerCase() == "img" || e.target.nodeName.toLowerCase() == "span") {
                    var fig = e.target.parentNode;
                    var bigfig = fig.cloneNode(true);
                    bigfig.className = "bigfig";
                    document.body.appendChild(bigfig);
                    var bfi = bigfig.querySelector("img");
                    bfi.onload = function() {
                        fpc = bfi.dataset.face.split(",").map(v => { return parseFloat(v); })
                        var span = bigfig.querySelector("span");
                        var fw = parseInt(window.getComputedStyle(bigfig, null).width); // offset* includes the border
                        var fh = parseInt(window.getComputedStyle(bigfig, null).height);
                        var scalex = bfi.offsetWidth / fw;
                        var scaley = bfi.offsetHeight / fh;
                        span.style.top = (fpc[1] * scaley) + "%";
                        span.style.height = (fpc[3] * scaley) + "%";
                        span.style.left = (fpc[0] * scalex) + "%";
                        span.style.width = (fpc[2] * scaley) + "%";
                    }
                    bfi.src = bfi.dataset.full;
                    bigfig.onclick = function(e) {
                        e.stopPropagation();
                        bigfig.remove();
                    }
                }
            }
            </script>""")
        fp.write("</body></html>")
