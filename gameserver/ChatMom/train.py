#!/usr/bin/env python

from __future__ import absolute_import

import tensorflow as tf
import numpy as np
import os
import time
import datetime
import logging
import input
from text_cnn import TextCNN

# TRAIN:
# train.py --loss_asymmetry=1.0 [--resume=<snapshot>]

# APPLY:
# train.py --resume=<snapshot> --infer=- --quiet=1
# Input strings to stdin, get probability of positive detection on stdout (one per line)

# Parameters
# ==================================================

home_dir = os.path.dirname(os.path.realpath(__file__))

# Model Hyperparameters
tf.flags.DEFINE_string("unit_mode", "characters", "Operate on characters or words (default: characters)")
tf.flags.DEFINE_boolean("chat_filter", True, "Apply rule-based ChatFilter on input (default: True)")
tf.flags.DEFINE_integer("embedding_dim", 3, "Dimensionality of input embedding (default: 3)")
tf.flags.DEFINE_string("filter_sizes", "3,5,7", "Comma-separated filter sizes (default: '3,5,7')")
tf.flags.DEFINE_integer("num_filters", 128, "Number of filters per filter size (default: 128)")
tf.flags.DEFINE_float("dropout_keep_prob", 0.5, "Dropout keep probability (default: 0.5)")
tf.flags.DEFINE_integer("hidden_layers", 1, "Number of hidden fully-connected layers (default: 1)")
tf.flags.DEFINE_integer("hidden_layer_size", 512, "Number of neurons in hidden fully-connected layers (default: 512)")
tf.flags.DEFINE_float("l2_reg_lambda", 0.0, "L2 regularization lambda (default: 0.0)")
tf.flags.DEFINE_float("loss_asymmetry", 0.0, "False positive/negative loss asymmetry (default: 0.0)")
# positive loss_asymmetry penalizes false positives more than false negatives

# Training parameters
tf.flags.DEFINE_integer("batch_size", 1024, "Batch Size (default: 1024)")
tf.flags.DEFINE_integer("num_epochs", 400, "Number of training epochs (default: 400)")
tf.flags.DEFINE_integer("evaluate_every", 20, "Evaluate model on dev set after this many steps (default: 100)")
tf.flags.DEFINE_integer("checkpoint_every", 100, "Save model after this many steps (default: 100)")
# Misc Parameters
tf.flags.DEFINE_integer("parallel", 4, "Thread parallelism (default: 4)")
tf.flags.DEFINE_boolean("allow_soft_placement", True, "Allow device soft device placement")
tf.flags.DEFINE_boolean("log_device_placement", False, "Log placement of ops on devices")
tf.flags.DEFINE_string("resume", "", "Path to checkpoint to resume (default: None)")
tf.flags.DEFINE_string("infer", "", "Path to file (- for stdin) to infer badness probability on (default: None)")
tf.flags.DEFINE_boolean("dry_run", False, "Don't mutate anything on disk")
tf.flags.DEFINE_boolean("quiet", False, "Critical output only")

FLAGS = tf.flags.FLAGS
if FLAGS.infer:
    FLAGS.num_epochs = 1
    FLAGS.dry_run = True # infer implies dry-run

if FLAGS.quiet:
    logging.basicConfig(level = logging.ERROR)
else:
    print("\nParameters:")
    for attr, value in sorted(FLAGS.__flags.iteritems()):
        print("{}={}".format(attr.upper(), value))
    print("")

class ANSIColor:
    BOLD = '\033[1m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    @classmethod
    def bold(self, x): return self.BOLD+x+self.ENDC
    @classmethod
    def red(self, x): return self.RED+x+self.ENDC
    @classmethod
    def green(self, x): return self.GREEN+x+self.ENDC
    @classmethod
    def yellow(self, x): return self.YELLOW+x+self.ENDC

# Data Preparatopn
# ==================================================

# Load data

# Load saved parameters that depend on training set
if FLAGS.resume:
    saved_vocab_inv = open(os.path.join(home_dir, "runs", FLAGS.resume, "vocabulary_inv.txt")).read().split("\n")
    saved_sequence_length = int(open(os.path.join(home_dir, "runs", FLAGS.resume, "sequence_length.txt")).read().strip())
else:
    saved_vocab_inv = None
    saved_sequence_length = None

x, y, vocabulary, vocabulary_inv = input.load_data(os.path.join(home_dir, "data"),
                                                   FLAGS.unit_mode, FLAGS.chat_filter,
                                                   saved_vocab_inv, saved_sequence_length,
                                                   FLAGS.infer)

if FLAGS.infer:
    x_train, x_dev = None, x
    y_train, y_dev = None, y
else:
    # Randomly shuffle data for training
    np.random.seed(10)
    shuffle_indices = np.random.permutation(np.arange(len(y)))
    x_shuffled = x[shuffle_indices]
    y_shuffled = y[shuffle_indices]
    # Split train/test set
    # TODO: This is very crude, should use cross-validation
    holdout_split = 0.05
    holdout_N = int(len(y) * holdout_split)
    x_train, x_dev = x_shuffled[:-holdout_N], x_shuffled[-holdout_N:]
    y_train, y_dev = y_shuffled[:-holdout_N], y_shuffled[-holdout_N:]

if not FLAGS.quiet:
    print("X Shape: {:}".format(x.shape))
    print("Vocabulary Size: {:d}".format(len(vocabulary)))
    if not FLAGS.infer:
        print("Train/Dev split: {:d}/{:d}".format(len(y_train), len(y_dev)))


# Training
# ==================================================

with tf.Graph().as_default():
    session_conf = tf.ConfigProto(
        inter_op_parallelism_threads=FLAGS.parallel,
        intra_op_parallelism_threads=FLAGS.parallel,
        allow_soft_placement=FLAGS.allow_soft_placement,
        log_device_placement=FLAGS.log_device_placement)
    sess = tf.Session(config=session_conf)
    with sess.as_default():
        cnn = TextCNN(
            sequence_length=saved_sequence_length or x_train.shape[1],
            num_classes=2,
            vocab_size=len(vocabulary),
            embedding_size=FLAGS.embedding_dim,
            filter_sizes=map(int, FLAGS.filter_sizes.split(",")),
            num_filters=FLAGS.num_filters,
            hidden_layers=FLAGS.hidden_layers,
            hidden_layer_size=FLAGS.hidden_layer_size,
            l2_reg_lambda=FLAGS.l2_reg_lambda,
            loss_asymmetry=FLAGS.loss_asymmetry)

        # Define Training procedure
        global_step = tf.Variable(0, name="global_step", trainable=False)
        optimizer = tf.train.AdamOptimizer(1e-4)
        grads_and_vars = optimizer.compute_gradients(cnn.loss)
        train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step)

        # Keep track of gradient values and sparsity (optional)
        grad_summaries = []
        for g, v in grads_and_vars:
            if g is not None:
                grad_hist_summary = tf.histogram_summary("{}/grad/hist".format(v.name), g)
                sparsity_summary = tf.scalar_summary("{}/grad/sparsity".format(v.name), tf.nn.zero_fraction(g))
                grad_summaries.append(grad_hist_summary)
                grad_summaries.append(sparsity_summary)
        grad_summaries_merged = tf.merge_summary(grad_summaries)

        # Summaries for loss and accuracy
        loss_summary = tf.scalar_summary("loss", cnn.loss)
        acc_summary = tf.scalar_summary("accuracy", cnn.accuracy)
        train_summary_op = tf.merge_summary([loss_summary, acc_summary, grad_summaries_merged])
        dev_summary_op = tf.merge_summary([loss_summary, acc_summary])

        # Output directory for models and summaries
        if not FLAGS.dry_run:
            timestamp = str(int(time.time()))
            out_dir = os.path.abspath(os.path.join(home_dir, "runs", timestamp))
            print("Writing to {}\n".format(out_dir))

            # Train Summaries
            train_summary_dir = os.path.join(out_dir, "summaries", "train")
            train_summary_writer = tf.train.SummaryWriter(train_summary_dir, sess.graph_def)

            # Dev summaries
            dev_summary_dir = os.path.join(out_dir, "summaries", "dev")
            dev_summary_writer = tf.train.SummaryWriter(dev_summary_dir, sess.graph_def)

            # Checkpoint directory. Tensorflow assumes this directory already exists so we need to create it
            checkpoint_dir = os.path.abspath(os.path.join(out_dir, "checkpoints"))
            checkpoint_prefix = os.path.join(checkpoint_dir, "model")
            if not FLAGS.dry_run and not os.path.exists(checkpoint_dir):
                os.makedirs(checkpoint_dir)

            # save vocabulary_inv for future use
            with open(os.path.join(out_dir, "vocabulary_inv.txt"), "w") as fd:
                fd.write("\n".join(vocabulary_inv))
            with open(os.path.join(out_dir, "sequence_length.txt"), "w") as fd:
                fd.write("{}\n".format(cnn.sequence_length))
        else:
            train_summary_writer = dev_summary_writer = None

        saver = tf.train.Saver(tf.all_variables())

        # Initialize all variables
        if FLAGS.resume:
            ckpt = tf.train.get_checkpoint_state(os.path.join(home_dir, "runs", FLAGS.resume, "checkpoints"))
            if not (ckpt and ckpt.model_checkpoint_path):
                raise Exception("checkpoint not found: {}".format(FLAGS.resume))
            saver.restore(sess, ckpt.model_checkpoint_path)
        else:
            sess.run(tf.initialize_all_variables())

        def train_step(x_batch, y_batch, epoch, batch_num, writer=None):
            """
            A single training step
            """
            feed_dict = {
              cnn.input_x: x_batch,
              cnn.input_y: y_batch,
              cnn.dropout_keep_prob: FLAGS.dropout_keep_prob
            }
            start_time = time.time()
            _, step, summaries, loss, accuracy = sess.run(
                [train_op, global_step, train_summary_op, cnn.loss, cnn.accuracy],
                feed_dict)
            end_time = time.time()
            time_str = datetime.datetime.now().isoformat()
            speed = len(x_batch)/(end_time - start_time)
            print("{}: epoch {} batch {} step {}, loss {:g}, acc {:g}, speed {:1f}".format(time_str, epoch, batch_num, step, loss, accuracy, speed))
            if writer:
                writer.add_summary(summaries, step)

        def dev_step(x_batch, y_batch, writer=None):
            """
            Evaluates model on a dev set
            """
            feed_dict = {
              cnn.input_x: x_batch,
              cnn.input_y: y_batch,
              cnn.dropout_keep_prob: 1.0
            }
            step, summaries, loss, scores, predictions, accuracy = sess.run(
                [global_step, dev_summary_op, cnn.loss, cnn.scores, cnn.predictions, cnn.accuracy],
                feed_dict)
            time_str = datetime.datetime.now().isoformat()

            if 1:
                for i in xrange(len(x_batch)):
                    decoded_sentence = ''.join([vocabulary_inv[x] for x in x_batch[i] if vocabulary_inv[x] != '<PAD/>'])
                    true_sentiment = np.argmax(y_batch[i])
                    logit = scores[i][1] # probability of positive
                    prob = np.exp(logit)/(1+np.exp(logit)) #XXX softmax?

                    if FLAGS.quiet:
                        ui_output = "{:.4f}".format(prob)
                    else:
                        ui_output = "{} -> TRUE {} PRED {} PROB {:2f}".format(decoded_sentence, true_sentiment, predictions[i], prob)
                        if true_sentiment == predictions[i]:
                            ui_output = ANSIColor.green(ui_output)
                        elif not true_sentiment and predictions[i]:
                            ui_output = ANSIColor.red(ui_output)
                        else:
                            ui_output = ANSIColor.yellow(ui_output)

                    print(ui_output)

            if not FLAGS.quiet:
                print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
            if writer:
                writer.add_summary(summaries, step)

        if FLAGS.infer:
            dev_step(x_dev, y_dev)
        else:
            # Generate batches
            batches = input.batch_iter(
                zip(x_train, y_train), FLAGS.batch_size, FLAGS.num_epochs)
            # Training loop. For each batch...
            for epoch, batch_num, batch in batches:
                x_batch, y_batch = zip(*batch)
                train_step(x_batch, y_batch, epoch, batch_num, writer=train_summary_writer)
                current_step = tf.train.global_step(sess, global_step)
                if current_step % FLAGS.evaluate_every == 0:
                    print("\nEvaluation:")
                    dev_step(x_dev, y_dev, writer=dev_summary_writer)
                    print("")
                if not FLAGS.dry_run and (current_step % FLAGS.checkpoint_every == 0):
                    path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                    print("Saved model checkpoint to {}\n".format(path))
