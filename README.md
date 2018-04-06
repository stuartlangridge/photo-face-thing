# Face recognition, grouping, and tagging, on a big list of images

There are a number of stages.

## Stage 1: get a list of images

We obtain a big list of image filenames from somewhere: maybe the contents of a folder, or from Shotwell, or whatever. Create SQLite entries for each.

## Stage 2: summary information

For each image, get the following:

* filename (we already have this)
* md5 hash (convenient unique key)
* face_encodings (128-dimensional numpy arrays, produced by `np.array(PIL.Image.open(filename))`), which is what face_`recognition.load_image_file` does
* thumbnail (nautilus etc may have already created one; if it hasn't, create one now)
* face_locations (top, left, bottom, right as pixels, and as percentages of image size, so they can be applied when an image is resized for display)

and store these in SQLite. Note that an image may have more than one face, and so images and faces must be stored separately and linked.

## Stage 3: pairing

For each pair of faces, calculate their face distance: this is done as `np.linalg.norm(fe2-fe1)` and store in SQLite.

### Sidebar: how face distance works

Each `face_encoding` is a 128-dimensional vector; that is, each face is categorised in each of 128 different characteristics. Then, how "similar" two faces are is defined by the magnitude of the vector between endpoints of the two face vectors: how far apart those two endpoints are. We get this by subtracting one vector from the other (thus giving us the vector that joins the two) and then calculating its length (using Pythagoras, which works in multiple dimensions). `fe2-fe1` is just subtracting the two vectors, and then `np.linalg.norm` does the Pythagoras calculation (square root of the sum of the squares of the quantities, so `np.linalg.norm(np.array([3,4])) == 5`).

## Stage 4: grouping

Find all pairs with face distance less than a threshold (the `face_recognition` library recommends 0.6 although we use 0.5). Then, go through each of these pairs and add them to groups, so that all "close" images end up together. Pseudocode:

```
for f1, f2 in facepairs:
    if f1 in a group and f2 in a group:
        if those are the same group:
            continue # nothing to do
        if those are different groups:
            combine the two groups into one
    else if f1 in a group and f2 not:
        add f2 to f1's group
    else if f2 in a group and f1 not:
        add f1 to f2's group
    else:
        create a new group and put f1 and f2 in it
```

At this point, user activity is needed to name the groups appropriately.

Note that this method will not group any image which doesn't match any other. So there are no groups of size 1, and any face which matches no other face (either correctly or incorrectly) will not be in any group at all and therefore won't be tagged.
