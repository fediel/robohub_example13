#==============================================================================
#
# Copyright (c) 2026, Qualcomm Innovation Center, Inc. All rights reserved.
# 
# SPDX-License-Identifier: BSD-3-Clause
#
#==============================================================================

import os
import cv2
import numpy as np

from utils import eqprocess, sigmoid
import infertoypy

class SAM2(object):
    def __init__(self, model_path):
        self.model = infertoypy.InferToy()
        res = self.model.init([
            "qnn-sample-app",
            "--retrieve_context", model_path,
            "--backend", os.path.join(os.environ['ADSP_LIBRARY_PATH'], "libQnnHtp.so"),
            "--system_library", os.path.join(os.environ['ADSP_LIBRARY_PATH'], "libQnnSystem.so"),
            "--log_level", "error"
        ])

        self.mean_data = (123.675, 116.28, 103.53)
        self.std_data = (58.395, 57.12, 57.375)

    def __call__(self, frame, threshold = 0.8):
        anti_size = max(frame.shape[:2])
        img, scale = eqprocess(frame, 352, 352)
        img = (img - self.mean_data) / self.std_data
        img = img.astype(np.float32)

        result = self.model.set(0, img)
        result = self.model.run()
        qnn_out, data_len = self.model.get(0)
        res = sigmoid(qnn_out.reshape(352,352))
        res = (res - res.min()) / (res.max() - res.min() + 1e-8)
        res = cv2.resize(res, (anti_size, anti_size))[:frame.shape[0], :frame.shape[1]]
        mask = (res > threshold)
        mask = mask.astype('uint8')
        return mask

    def __del__(self):
        self.model.destroy()
