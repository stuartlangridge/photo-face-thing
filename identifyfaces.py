#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf, Gdk, GLib


import core

class MyWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Identify faces")
        self.gf = core.get_groups_and_faces()

        self.img = Gtk.Image()
        self.counter = Gtk.Label()
        self.debounce = 0

        prev = Gtk.Button(label="<")
        prev.connect("clicked", self.previous)
        nxt = Gtk.Button(label=">")
        nxt.connect("clicked", self.nxt)
        self.entry = Gtk.Entry()
        self.entry.connect("key-release-event", self.kp)

        vb = Gtk.VBox(spacing=10)
        vb.add(self.img)
        vb.add(self.counter)
        hb = Gtk.HBox(spacing=10)
        hb.add(prev)
        hb.add(self.entry)
        hb.add(nxt)
        vb.add(hb)

        self.add(vb)
        self.image_index = 0
        self.load()

        self.show_all()

    def update(self, text, groupid, image_index):
        core.update_groupname(groupid, text)
        print("Save text", text, groupid)
        self.gf[image_index]["groupname"] = text
        self.debounce = 0
        return False
    def kp(self, entry, key):
        if self.debounce: GLib.source_remove(self.debounce)
        self.debounce = GLib.timeout_add_seconds(1, self.update, entry.get_text(), self.gf[self.image_index]["groupid"], self.image_index)
    def previous(self, *args):
        if self.image_index > 0:
            self.image_index -= 1
            self.load()
    def nxt(self, *args):
        if self.image_index < len(self.gf) - 1:
            self.image_index += 1
            self.load()
    def load(self):
        img = self.gf[self.image_index]
        self.counter.set_text("{}/{}".format(self.image_index + 1, len(self.gf)))
        # load whole image into a pixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(img["image"])
        # grab the face out of it
        face = pb.new_subpixbuf(img["x"], img["y"], img["w"], img["h"])
        # scale that so it fits in a 400x400 box
        if img["w"] > img["h"]:
            scalew = 400
            scaleh = int(img["h"] * 400.0 / img["w"])
        else:
            scaleh = 400
            scalew = int(img["w"] * 400.0 / img["h"])
        sface = face.scale_simple(scalew, scaleh, GdkPixbuf.InterpType.BILINEAR)
        self.img.set_from_pixbuf(sface)
        gn = img.get("groupname")
        if not gn: gn = ""
        self.entry.set_text(gn)

win = MyWindow()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()