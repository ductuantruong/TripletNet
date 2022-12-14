# https://github.com/amdegroot/ssd.pytorch/blob/master/data/voc0712.py
# https://github.com/fmassa/vision/blob/voc_dataset/torchvision/datasets/voc.py

import os
import cv2
import numpy as np 
from PIL import Image

import xml.etree.ElementTree as ET 

import torch.utils.data
from utils.transform import *


class VOC(object):
    N_CLASSES = 20
    CLASSES = (
        'aeroplane', 'bicycle', 'bird', 'boat',
        'bottle', 'bus', 'car', 'cat', 'chair',
        'cow', 'diningtable', 'dog', 'horse',
        'motorbike', 'person', 'pottedplant',
        'sheep', 'sofa', 'train', 'tvmonitor'
    )

    MEAN = [123.68, 116.779, 103.939]   # R,G,B

    label_to_id = dict(map(reversed, enumerate(CLASSES))) 
    id_to_label = dict(enumerate(CLASSES)) 


class Viz(object):
    def __init__(self):
        voc = VOC()

        classes = voc.CLASSES

        self.id_to_label = voc.id_to_label
        self.label_to_id = voc.label_to_id

        colors = {}
        for label in classes:
            id = self.label_to_id[label]
            color = self._to_color(id, len(classes))
            colors[id] = color
            colors[label] = color
        self.colors =colors

    def _to_color(self, indx, n_classes):
        base = int(np.ceil(pow(n_classes, 1./3)))
        base2 = base * base
        b = 2 - indx / base2
        r = 2 - (indx % base2) / base
        g = 2 - (indx % base2) % base
        return (r * 127, g * 127, b * 127)

    def draw_bbox(self, img, bboxes, labels, relative=False):
        if len(labels) == 0:
            return img
        img = img.copy()
        h, w = img.shape[:2]

        if relative:
            bboxes = bboxes * [w, h, w, h]

        bboxes = bboxes.astype(np.int)
        labels = labels.astype(np.int)

        for bbox, label in zip(bboxes, labels):
            left, top, right, bot = bbox
            color = self.colors[label]
            label = self.id_to_label[label]
            cv2.rectangle(img, (left, top), (right, bot), color, 2)
            cv2.putText(img, label, (left+1, top-5), cv2.FONT_HERSHEY_DUPLEX, 0.4, color, 1, cv2.LINE_AA)

        return img

    def blend_segmentation(self, img, target):
        mask = (target.max(axis=2) > 0)[..., np.newaxis] * 1.
        blend = img * 0.3 +  target * 0.7
        
        img = (1 - mask) * img + mask * blend
        return img.astype('uint8')



class ParseAnnotation(object):
    def __init__(self, keep_difficult=True):
        self.keep_difficult = keep_difficult

        voc = VOC()
        self.label_to_id = voc.label_to_id
        self.classes = voc.CLASSES

    def __call__(self, target):
        tree = ET.parse(target).getroot()

        bboxes = []
        labels = []
        for obj in tree.iter('object'):
            difficult = int(obj.find('difficult').text) == 1
            if not self.keep_difficult and difficult:
                continue

            label = obj.find('name').text.lower().strip()
            if label not in self.classes:
                continue
            label = self.label_to_id[label]

            bndbox = obj.find('bndbox')
            bbox = [int(bndbox.find(_).text) - 1 for _ in ['xmin', 'ymin', 'xmax', 'ymax']]

            bboxes.append(bbox)
            labels.append(label)

        return np.array(bboxes), np.array(labels)



class VOCDataset(torch.utils.data.Dataset):
    def __init__(self, root, image_set, keep_difficult=False, transform=None, target_transform=None):
        self.root = root
        self.image_set = image_set
        self.transform = transform
        self.target_transform = target_transform

        self._imgpath = os.path.join('%s', 'JPEGImages', '%s.jpg')
        self._annopath = os.path.join('%s', 'Annotations', '%s.xml')
        self._segpath = os.path.join('%s', 'SegmentationClass', '%s.png')

        self.parse_annotation = ParseAnnotation(keep_difficult=keep_difficult)

        self.ids = []
        for year, split in image_set:
            basepath = os.path.join(self.root, 'VOC' + str(year))
            path = os.path.join(basepath, 'ImageSets', 'Main')
            for file in os.listdir(path):
                if not file.endswith('_' + split + '.txt'):
                    continue
                with open(os.path.join(path, file)) as f:
                    for line in f:
                        self.ids.append((basepath, line.strip()[:-3]))

        self.ids = sorted(list(set(self.ids)), key=lambda _:_[0]+_[1])  # deterministic 

    def __getitem__(self, index):
        img_id = self.ids[index]

        img = cv2.imread(self._imgpath % img_id)[:, :, ::-1]
        bboxes, det_labels = self.parse_annotation(self._annopath % img_id)
        

        if os.path.exists(self._segpath  % img_id):
            seg_labels = Image.open(self._segpath % img_id)
            seg_labels = np.array(seg_labels, dtype=np.uint8)
        else:
            seg_labels = np.zeros((img.shape[0], img.shape[1])) + 255
        bboxes, det_labels = self.filter(img, bboxes, det_labels)
        if self.transform is not None:
            img, bboxes, seg_labels = self.transform(img, bboxes, seg_labels)

        if self.target_transform is not None:
            bboxes, det_labels = self.target_transform(bboxes, det_labels)

        return img, bboxes, det_labels, torch.as_tensor(seg_labels, dtype=torch.long)

    def __len__(self):
        return len(self.ids)

    def filter(self, img, boxes, labels):
        shape = img.shape
        if len(shape) == 2:
            h, w = shape
        else:   # !!
            if shape[0] > shape[2]:   # HWC
                h, w = img.shape[:2]
            else:                     # CHW
                h, w = img.shape[1:]

        boxes_ = []
        labels_ = []
        for box, label in zip(boxes, labels):
            if min(box[2] - box[0], box[3] - box[1]) <= 0:
                continue
            if np.max(boxes) < 1 and np.sqrt((box[2] - box[0]) * w * (box[3] - box[1]) * h) < 8:
                continue
            boxes_.append(box)
            labels_.append(label)
        return np.array(boxes_), np.array(labels_)
        