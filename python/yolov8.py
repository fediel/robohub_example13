#==============================================================================
#
# Copyright (c) 2026, Qualcomm Innovation Center, Inc. All rights reserved.
# 
# SPDX-License-Identifier: BSD-3-Clause
#
#==============================================================================

import os
import numpy as np

from utils import eqprocess, xywh2xyxy, NMS, process_mask, masks2segments
import infertoypy

class Yolov8Seg(object):
    def __init__(self, model_path, width, height, class_num):
        self.class_num = class_num
        self.width = width
        self.height = height

        self.blocks = int(height * width * ( 1 / 64 + 1 / 256 + 1 / 1024))
        self.maskw = int(width / 4)
        self.maskh = int(height / 4)


        self.model = infertoypy.InferToy()
        res = self.model.init([
            "qnn-sample-app",
            "--retrieve_context", model_path,
            "--backend", os.path.join(os.environ['ADSP_LIBRARY_PATH'], "libQnnHtp.so"),
            "--system_library", os.path.join(os.environ['ADSP_LIBRARY_PATH'], "libQnnSystem.so"),
            "--log_level", "error",
        ])

    def __call__(self, frame, conf_threshold = 0.6, iou_threshold = 0.5):
        img, scale = eqprocess(frame, self.height, self.width)
        img = img /255.
        img = img.astype(np.float32)

        res = self.model.set(0, img)
        self.model.run()

        protos, data_len = self.model.get(0)
        input0_data, data_len = self.model.get(3)
        input1_data, data_len = self.model.get(2)
        input2_data, data_len = self.model.get(1)
        
        input0_data = input0_data.reshape(1, 4, self.blocks)
        input1_data = input1_data.reshape(1, self.class_num, self.blocks)
        input2_data = input2_data.reshape(1, 32, self.blocks)
        protos = protos.reshape(1, self.maskh, self.maskw, 32).transpose(0,3,1,2)
        
        boxes = np.concatenate([input0_data, input1_data, input2_data], axis = 1)
        x = boxes.transpose(0,2,1)
        x = x[np.amax(x[..., 4:-32], axis=-1) > conf_threshold]

        if len(x) > 0:
            x = np.c_[x[..., :4], np.amax(x[..., 4:-32], axis=-1), np.argmax(x[..., 4:-32], axis=-1), x[..., -32:]]
            x[:, :4] = xywh2xyxy(x[:, :4])
            index = NMS(x[:, :4], x[:, 4], iou_threshold)
            out_boxes = x[index]
            out_boxes[..., :4] = out_boxes[..., :4]  * scale
            masks = process_mask(protos[0], out_boxes[:, -32:], out_boxes[:, :4], frame.shape)
            segments = masks2segments(masks)
            return out_boxes, segments
        return None, None
    
    def __del__(self):
        self.model.destroy()