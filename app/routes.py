
from app import app
from flask import send_file, request
import hashlib
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import pprint
import numpy
import os
import random
import boto3
import time

@app.route('/', methods=['GET'])
@app.route('/index')
def index():
    return send_file('static/form.html')

@app.route('/isu.jpg', methods=['GET'])
def target_image():
    return send_file('static/isu.jpg')

@app.route('/collider', methods=['POST'])
def collider():
    files = request.files.getlist('files')
    if len(files) != 2:
        return "I need exactly two files, please."

    hashes_1 = get_hashes(files[0])
    hashes_2 = get_hashes(files[1])

    if hashes_1["md5"] != hashes_2["md5"] and hashes_1["sha1"] != hashes_2["sha1"]:
        return "Sorry, I need two files with the same hash (MD5 or SHA1)"

    # At this point, either sha1 or md5 matches on the files, are they jpegs?

    with open('app/static/isu.jpg', 'rb') as f:
        target_image = image_parse(f)
    assert target_image is not None

    im1 = image_parse(files[0])
    im2 = image_parse(files[1])

    if im1 is None or im2 is None:
        save_them(files[0], files[1])
        return "Sorry, one of your images isn't parsable as jpeg"

    # Are they the same size as our target image?
    if (
        im1.size[0] != im2.size[0]
        or im1.size[1] != im2.size[1]
        or target_image.size[0] != im1.size[0]
        or target_image.size[1] != im2.size[1]
    ):
        save_them(files[0], files[1])
        return "Sorry, the image must be the same size in pixels along both dimensions"

    goodOne = None
    badOne = None

    # Do they look sufficiently the same? Or sufficiently different?

    target_gray = target_image.convert("L")

    alikes = []

    alike = None
    try:
        alike = compare_images(target_image, im1, target_gray)
        if alike >= 0.99:
            goodOne = im1
        elif alike <= 0.76:
            badOne = im1
    except ImageComparisonException as e:
        save_them(files[0], files[1])
        return str(e)

    alikes.append(alike)

    alike = None
    try:
        alike = compare_images(target_image, im2, target_gray)
        if alike >= 0.99 and goodOne is None:
            goodOne = im2
        elif alike <= 0.76 and badOne is None:
            badOne = im2
    except ImageComparisonException as e:
        save_them(files[0], files[1])
        return str(e)

    alikes.append(alike)

    if badOne is None:
        save_them(files[0], files[1])
        return f"Sorry, one image should be very different from mine {alikes[0]} {alikes[1]}"

    if goodOne is None:
        save_them(files[0], files[1])
        return f"Sorry, one image should be very similiar to mine {alikes[0]} {alikes[1]}"

    # Similiarity should be transitive, right? Just check it and make sure.
    try:
        if compare_images(im1, im2) >= 0.76:
            save_them(files[0], files[1])
            return "Sorry, your images are too similiar to each other"
    except ImageComparisonException as e:
        return str(e)

    # The user has met the challenge, give up the key...

    save_them(files[0], files[1], success=True)

    if hashes_1["md5"] == hashes_2["md5"]:
        with open("key.md5", "r") as f:
            return f.read()

    if hashes_1["sha1"] == hashes_2["sha1"]:
        with open("key.sha1", "r") as f:
            return f.read()

class ImageComparisonException(Exception):
    pass

def compare_images(im1, im2, im1gray=None, im2gray=None):
    if im1.size != im2.size:
        print(im1.size, im2.size)
        raise ImageComparisonException("images are not the right size")

    if im2.getbands() != im2.getbands():
        raise ImageComparisonException("incorrect or missing color bands")

    # convert both images to grayscale if not already available
    if im1gray is None:
        im1gray = im1.convert("L")
    if im2gray is None:
        im2gray = im2.convert("L")

    pixels1 = numpy.array(im1gray.getdata()) / 255.0
    pixels2 = numpy.array(im2gray.getdata()) / 255.0
    return ssim(pixels1, pixels2)

def get_hashes(file):
    """Get the hashes for a fileobj (in one pass)"""
    hashfunnames = ("md5", "sha1", "sha256")
    hashfuns = [hashlib.new(f) for f in hashfunnames]
    while True:
        buf = file.read(8192)
        if len(buf) == 0:
            break
        for h in hashfuns:
            h.update(buf)

    file.seek(0)

    res = {}
    for i in range(len(hashfunnames)):
        res[hashfunnames[i]] = hashfuns[i].hexdigest()
    return res

def image_parse(file):
    # Cheap hack, open the image and try to turn it into a thumbnail.
    # if any of that fails, it's not parsable as jpeg
    try:
        im = Image.open(file, mode="r", formats=["jpeg"])
        im.copy().thumbnail((128, 128))
        file.seek(0)
        return im
    except:
        return None

def save_them(file1, file2, success=False):
    rnd = '%032x' % random.SystemRandom().randrange(16**32)
    stamp = '%d' % int(time.time())

    save_file(file1, success, 1, rnd, stamp)
    save_file(file2, success, 2, rnd, stamp)

def save_file(filedata, success, fileno, rnd, stamp):
    basename = 'fail'
    if success:
        basename = 'success'

    dstname = f"hashcollider/{basename}-{stamp}-{rnd}-{fileno}.jpg"
    s3 = boto3.client('s3')
    filedata.seek(0)
    s3.upload_fileobj(filedata, 'saintcon-hc-2022-jlw-store', dstname)
