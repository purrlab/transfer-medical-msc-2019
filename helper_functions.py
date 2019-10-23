import numpy as np
import os
import pandas
import matplotlib.pyplot as plt
import json
import glob
import cv2
import random
import tensorflow as tf
import models
import gc
import datetime
from sklearn.metrics import roc_curve, confusion_matrix, roc_auc_score
from keras.optimizers import SGD, RMSprop, Adam
from keras.preprocessing.image import ImageDataGenerator
from keras.layers import Input
from keras.backend.tensorflow_backend import set_session
from keras.backend.tensorflow_backend import clear_session
from keras.backend.tensorflow_backend import get_session
from keras.callbacks import EarlyStopping
from keras import backend as K
from time import time
import tensorflow

def limit_memory():
    # release unused memory sources, force garbage collection
    K.clear_session()
    K.get_session().close()
    tf.reset_default_graph()
    gc.collect()
    #cfg = tf.ConfigProto()
    #cfg.gpu_options.allow_growth = True
    #keras.backend.set_session(tf.Session(config=cfg))
    K.set_session(tf.Session())
    gc.collect()


def train_model(config, learning_rate, dropout_rate, l2_rate, batchsize, gen_obj_training, gen_obj_test):
    # get timestamp for saving stuff
    timestamp = datetime.datetime.now().strftime("%y%m%d_%Hh%M")

    # set seed
    sd = 28

    # define the optimizer
    adam = Adam(lr=learning_rate)

    # get paths to training, validation and testing directories
    trainingpath = config['trainingpath']
    validationpath = config['validationpath']
    testpath = config['testpath']

    # get total number of images in each split, needed to train in batches
    num_training = len(glob.glob(os.path.join(trainingpath, '**/*.jpg')))
    num_validation = len(glob.glob(os.path.join(validationpath, '**/*.jpg')))
    num_test = len(glob.glob(os.path.join(testpath, '**/*.jpg')))


    # initialize the image generators that load batches of images
    gen_training = gen_obj_training.flow_from_directory(
        trainingpath,
        class_mode="binary",
        target_size=(224,224),
        color_mode="rgb",
        shuffle=True,
        batch_size=batchsize)

    gen_validation = gen_obj_test.flow_from_directory(
        validationpath,
        class_mode="binary",
        target_size=(224,224),
        color_mode="rgb",
        shuffle=False,
        batch_size=batchsize)

    gen_test = gen_obj_test.flow_from_directory(
        testpath,
        class_mode="binary",
        target_size=(224,224),
        color_mode="rgb",
        shuffle=False,
        batch_size=batchsize)

    input_tensor = Input(shape=(224,224,3))

    # load VGG16 model architecture
    model = models.model_VGG16(dropout_rate, l2_rate, input_tensor)

    # compile model
    model.compile(loss="binary_crossentropy", optimizer=adam, metrics=["accuracy"])

    # define early stopping criterion
    early_stopping = EarlyStopping(monitor='val_loss', patience=5, verbose=0, mode='auto', baseline=None, restore_best_weights=True)

    # get start time
    start_time = time()

    # train model
    hist = model.fit_generator(
        gen_training,
        steps_per_epoch = num_training // batchsize,
        validation_data = gen_validation,
        validation_steps = num_validation // batchsize,
        # class_weight=class_weights,
        epochs=50,
        verbose=2,
        callbacks=[early_stopping])

    # get training time
    train_time = time() - start_time

    # get number of epochs the training lasted for
    training_epochs = len(hist.history['loss'])

    # create plot directory if it doesn't exist and plot training progress
    print("saving plots...")
    if not os.path.exists(config['plot_path']):
        os.makedirs(config['plot_path'])
    plotpath = os.path.join(config['plot_path'], "{}_training.png".format(timestamp))
    plot_training(hist, training_epochs, plotpath)

    # reinitialize validation generator with batch size 1 so all validation images are used
    gen_validation = gen_obj_test.flow_from_directory(
        validationpath,
        class_mode="binary",
        target_size=(224,224),
        color_mode="rgb",
        shuffle=False,
        batch_size=1)

    # check the model on the validation data and use this for tweaking (not on test data)
    # this is for checking the best training settings; afterwards we can test on test set
    print("evaluating model...")

    # make predictions
    preds = model.predict_generator(gen_validation, verbose=1)

    # get true labels
    true_labels = gen_validation.classes

    # plot ROC and calculate AUC
    AUC, AUC2 = ROC_AUC(preds, true_labels, config, timestamp)

    return hist, AUC, AUC2, train_time, training_epochs, timestamp

def ROC_AUC(preds, true_labels, config, timestamp):
    # initialize TPR, FPR, ACC and AUC lists
    TPR_list, FPR_list, ACC_list = [], [], []
    AUC_score = []

    # preds is an array like [[x] [x] [x]], make it into array like [x x x]
    preds = np.asarray([label for sublist in preds for label in sublist])

    # calculate for different thresholds
    thresholds = -np.sort(-(np.unique(preds)))
    for threshold in thresholds:
        # apply threshold to predictions
        pred_labels = np.where(preds > threshold, 1, 0).astype(int)

        # calculate True Positive (TP), True Negative (TN), False Positive (FP) and
        # False Negative (FN)
        TP = np.sum(np.logical_and(pred_labels == 1, true_labels == 1))
        TN = np.sum(np.logical_and(pred_labels == 0, true_labels == 0))
        FP = np.sum(np.logical_and(pred_labels == 1, true_labels == 0))
        FN = np.sum(np.logical_and(pred_labels == 0, true_labels == 1))

        # calculate TPR, FPR, ACC and add to lists
        TPR = TP / (TP + FN)
        FPR = FP / (FP + TN)
        ACC = (TP + TN) / (TP + TN + FP + FN)

        TPR_list.append(TPR)
        FPR_list.append(FPR)
        ACC_list.append(ACC)

        AUC_score.append((1-FPR+TPR)/2)

        pred_labels = []

    AUC = round(sum(AUC_score)/len(thresholds),3)
    print("AUC: {}".format(AUC))

    AUC2 = round(roc_auc_score(true_labels, preds),3)
    print("sk_AUC: {}".format(AUC2))

    # plot and save ROC curve
    plt.style.use("ggplot")
    plt.figure()
    plt.plot(FPR_list, TPR_list)
    plt.plot([0,1],[0,1], '--')
    plt.xlabel("FPR")
    plt.ylabel("TPR")
    plt.xlim(0,1)
    plt.ylim(0,1)
    plt.title("ROC Curve, AUC = {}".format(AUC))
    plt.savefig(os.path.join(config['plot_path'], "{}_ROC.png".format(timestamp)))

    # also plot accuracies for each threshold
    plt.figure()
    plt.plot(thresholds, ACC_list)
    plt.plot([0,1],[0,1], '--')
    plt.xlabel("Threshold")
    plt.ylabel("Accuracy")
    plt.xlim(0,1)
    plt.ylim(0,1)
    plt.title("Accuracy per threshold")
    plt.savefig(os.path.join(config['plot_path'], "{}_ACC.png".format(timestamp)))

    # save plot data in csv file
    csvpath = os.path.join(config['model_savepath'], '{}_eval.csv'.format(timestamp))
    pandas.DataFrame([TPR_list, FPR_list, ACC_list]).to_csv(csvpath)

    return AUC, AUC2

def load_data(splitpath):
    data, labels = [], []

    # loop over the rows in data split file with extracted features
    for row in open(splitpath):
        # extract class label and features and add to lists
        row = row.strip().split(",")
        label = row[0]
        features = np.array(row[1:], dtype="float")

        data.append(features)
        labels.append(label)

    # convert lists to numpy arrays
    data = np.array(data)
    labels = np.array(labels)

    return (data, labels)

def plot_training(hist, epochs, plotpath):
    # plot and save training history
    plt.style.use("ggplot")
    plt.figure()
    plt.plot(np.arange(0, epochs), hist.history["loss"], label="train_loss")
    plt.plot(np.arange(0, epochs), hist.history["val_loss"], label="val_loss")
    plt.plot(np.arange(0, epochs), hist.history["acc"], label="train_acc")
    plt.plot(np.arange(0, epochs), hist.history["val_acc"], label="val_acc")
    plt.title("Training Loss and Accuracy")
    plt.xlabel("Epoch #")
    plt.ylabel("Loss/Accuracy")
    plt.legend(loc="upper right")
    plt.savefig(plotpath)

def load_training_data(trainingpath):
    # function to load training data
    images = []
    imagepaths = glob.glob(os.path.join(trainingpath, '**/*.jpg'))

    for path in imagepaths:
        images.append(cv2.imread(path))

    images = np.array(images)
    return images