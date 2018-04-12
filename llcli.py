#!/usr/bin/env python3
"The low-level command-line interface"
import argparse, sys
import core

def description(desc, order):
    def new_f(f):
        f.__cmd_desc__ = desc
        f.__cmd_order__ = desc
        return f
    return new_f


@description("Initialise the system", 0)
def cmd_init(overwrite):
    try:
        core.init(overwrite=="yes")
    except core.WontOverwriteError:
        print("Won't overwrite existing data file. Call as 'init yes' to overwrite.")

@description("Read image files from a folder", 1)
def cmd_read_folder(folder):
    count = core.load_from_folder(folder)
    print("Read names of {} images".format(count))

@description("Read image files from Shotwell", 1)
def cmd_read_shotwell():
    pass

@description("Analyse each image for faces", 2)
def cmd_parse_images():
    processed = 99
    while processed:
        processed, remaining = core.analyse_images_in_blocks()
        print("Processed {} images ({} remaining)".format(processed, remaining))

@description("Analyse all faces for closeness", 3)
def cmd_pair():
    core.insert_empty_pairs()
    processed = 99
    while processed:
        processed, remaining = core.pair_faces_in_blocks()
        print("Processed {} face pairs ({} remaining)".format(processed, remaining))

@description("Group similar faces together", 4)
def cmd_group():
    processed = 99
    while processed:
        processed, remaining = core.group_faces_in_blocks()
        print("Assigned {} faces to groups ({} remaining)".format(processed, remaining))

@description("Rename a group", 5)
def cmd_rename_group(before, after):
    pass

@description("Find the best face for each group", 6)
def cmd_best_face():
    core.find_best_faces()

@description("Make a very simple HTML gallery", 7)
def cmd_gallery(output):
    core.simple_gallery(output)

@description("Do a full load, from a folder, to a gallery (losing existing data without asking)", 7)
def cmd_all(folder, gallery_output):
    cmd_init("yes")
    cmd_read_folder(folder)
    cmd_parse_images()
    cmd_pair()
    cmd_group()
    cmd_best_face()
    cmd_gallery(gallery_output)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Photo name tagger")
    subparsers = parser.add_subparsers(help="commands", dest="command")
    subparsers.add_parser("help", help="This help")

    cmds = dict([(x[4:].replace("_", "-"), globals()[x]) for x in globals().keys() if x.startswith("cmd_")])
    for name, fn in sorted(cmds.items(), key=lambda x: getattr(x[1], "__cmd_order__", 99)):
        p = subparsers.add_parser(name, help=getattr(fn, "__cmd_desc__", "(undocumented)"))
        if fn.__code__.co_varnames:
            for a in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                p.add_argument(a, action="store")

    args = parser.parse_args()
    if args.command == "help":
        parser.print_help()
        sys.exit()

    args = dict(args._get_kwargs())
    cmd = args["command"]
    del args["command"]

    if cmd is None:
        parser.print_help()
        sys.exit()

    fn = cmds[cmd]
    fn(**args)





