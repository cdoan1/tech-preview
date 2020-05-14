#!/usr/bin/env python3

from os.path import dirname, abspath, getctime, isdir, isfile
from os import system
from glob import glob
import os
import sys
import getopt
import yaml
import json
from shutil import which


def skopeo_image_sync(image_remote, dryrun, pull_secret, image, dst_reg, ad_hoc_images=False):

    dst_rt = 'docker'
    src_rt = 'docker'

    if ad_hoc_images == False:
        if image_remote == '' or image_remote == None:
            src_reg = image['image-remote'].split('/')[0]
            src_ns = image['image-remote'].split('/')[1]
        else:
            src_reg = image_remote.split('/')[0]
            src_ns = image_remote.split('/')[1]

        src_image = image['image-name']
        digest = image['image-digest']
        tag = image['image-tag']
        complete_src_image = "%s://%s/%s/%s" % (
            src_rt, src_reg, src_ns, src_image)
        complete_dst_image = "%s://%s/%s/%s" % (
            dst_rt, dst_reg, src_ns, src_image)
        print("Syncing Images: ", image['image-name'])
        cmd = "skopeo copy %s@%s %s --authfile=%s --all" % (
            complete_src_image, digest, complete_dst_image, pull_secret)
    else:
        print("Syncing Extra Images: ", image.split("/", maxsplit=1)[1])
        complete_src_image = "%s://%s" % (src_rt, image)
        complete_dst_image = "%s://%s/%s" % (dst_rt,
                                             dst_reg, image.split("/", maxsplit=1)[1])
        cmd = "skopeo copy %s %s --authfile=%s" % (
            complete_src_image, complete_dst_image, pull_secret)

    print(cmd)

    if not dryrun:
        r = system(cmd)
        if r != 0:
            print("Failed!")
        else:
            print("Done!")
        print()


def oc_catalog_sync(catalog, cat_from, dst_reg, pull_secret, oc_version):
    priv_reg_prefix = 'local-operators'
    priv_reg_version = 'v1'
    complete_from = "%s:%s" % (cat_from, oc_version)
    complete_to = "%s/%s/%s:%s" % (dst_reg,
                                   priv_reg_prefix, catalog, priv_reg_version)

    cat_build = "oc adm catalog build --appregistry-org %s --from=%s --to=%s --registry-config=%s" % (
        catalog, complete_from, complete_to, pull_secret)
    system(cat_build)
    cat_mirror = "oc adm catalog mirror %s %s --registry-config=%s" % (
        complete_to, dst_reg, pull_secret)
    system(cat_mirror)


def generate_icsp(image, dst_reg, map_dict, ad_hoc_images=False):
    if ad_hoc_images == False:
        src_reg = image['image-remote'].split('/')[0]
        src_ns = image['image-remote'].split('/')[1]
        src_image = image['image-name']
        complete_src_image = "%s/%s/%s" % (src_reg, src_ns, src_image)
    else:
        complete_src_image = image

    mirror = {"mirrors": [dst_reg], "source": complete_src_image}
    map_dict['spec']['repositoryDigestMirrors'].append(mirror)

    return map_dict


def download_manifests():
    gist_url = "https://gist.githubusercontent.com/cdoan1/11302f6ebb48fc4c02097897fc116d50/raw/rc2-manifest.json"
    cmd = "curl %s -o ./rc2-manifest.json" % (gist_url)
    system(cmd)
    list_of_files = glob('.' + '/*.json')
    return max(list_of_files, key=getctime)


def sync_acm_images(image_remote, dryrun, map_dict, pull_secret, dst_reg, acm_json_manifest):
    r = which("skopeo")
    if r == None:
        print("You need to download the Skopeo Client! bye")
        sys.exit()

    extra_images = [
        "docker.io/library/busybox:1.28.0-glibc",
        "quay.io/coreos/etcd-operator:v0.9.4",
        "quay.io/coreos/etcd:v3.2.13"
    ]

    for image in extra_images:
        skopeo_image_sync(image_remote, dryrun,
                          pull_secret, image, dst_reg, True)
        map_dict = generate_icsp(image, dst_reg, map_dict, True)

    with open(acm_json_manifest) as f:
        data = json.load(f)
        for image in data:
            skopeo_image_sync(image_remote, dryrun,
                              pull_secret, image, dst_reg)
            map_dict = generate_icsp(image, dst_reg, map_dict)
        f.close()

    with open('99-acm-images-icsp.yaml', 'w') as outfile:
        yaml.dump(map_dict, outfile, allow_unicode=True)


def main(argv):

    dryrun = False
    dst_reg = ''
    pull_secret = ''
    image_remote = ''

    try:
        opts, args = getopt.getopt(argv, "m:dhp:", ["mirror=", "dryrun="])
    except getopt.GetoptError:
        print(
            'mirror_images.py -m <registry:5000> | --mirror <registry:5000> [ -d ]')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(
                '''
Usage:

mirror_images.py -m <registry:5000> | --mirror <registry:5000> [ -d ]
                 -r registry.redhat.io/example
'''
            )
            sys.exit()
        elif opt in ("-m", "--mirror"):
            dst_reg = arg
        elif opt in ("-p", "--pullsecret"):
            pull_secret = arg
        elif opt in ("-d"):
            dryrun = True
        elif opt in ("-r"):
            image_remote = arg

    file_path = dirname(abspath(__file__))

    map_dict = {
        "apiVersion": "operator.openshift.io/v1alpha1",
        "kind": "ImageContentSourcePolicy",
        "metadata": {
            "name": "acm-images-icsp"
        },
        "spec": {
            "repositoryDigestMirrors": []
        }
    }

    if pull_secret == '' or pull_secret == None:
        pull_secret = file_path + '/acmd-pull-secret.json'

    if not isfile(pull_secret) or pull_secret == '' or pull_secret == None:
        print("\nPull secret %s is required! bye!" % pull_secret)
        sys.exit()

    if dst_reg == '' or dst_reg == None:
        print("\nA mirror registry is required! bye")
        sys.exit()

    r = which("oc")
    if r == None:
        print("You need to download the OC Client! bye")
        sys.exit()

    print("00 pull_secret:", pull_secret)
    print("00 mirror registry:", dst_reg)

    acm_json_manifest = download_manifests()
    print("01 download manifest:", acm_json_manifest)

    print("02 sync images")
    sync_acm_images(image_remote, dryrun, map_dict,
                    pull_secret, dst_reg, acm_json_manifest)

    oc_version = 'v4.3'
    catalogs = ['community-operators',
                'redhat-operators', 'certified-operators']
    cat_from = 'registry.redhat.io/openshift4/ose-operator-registry'


if __name__ == "__main__":
    main(sys.argv[1:])
