import tensorflow as tf

class TextCNN(object):
    """
    A CNN for text classification.
    Uses an embedding layer, followed by a convolutional, max-pooling and softmax layer.
    """
    def __init__(
      self, sequence_length, num_classes, vocab_size,
      embedding_size, filter_sizes, num_filters,
      hidden_layers=0, hidden_layer_size=0,
      l2_reg_lambda=0.0, loss_asymmetry=0):
        self.sequence_length = sequence_length

        # Placeholders for input, output and dropout
        self.input_x = tf.placeholder(tf.int32 if embedding_size > 1 else tf.float32, [None, sequence_length], name="input_x")
        self.input_y = tf.placeholder(tf.float32, [None, num_classes], name="input_y")
        self.dropout_keep_prob = tf.placeholder(tf.float32, name="dropout_keep_prob")

        # Keeping track of l2 regularization loss (optional)
        l2_loss = tf.constant(0.0)

        # Embedding layer
        if embedding_size > 1:
            with tf.device('/cpu:0'), tf.name_scope("embedding"):
                W = tf.Variable(
                    tf.random_uniform([vocab_size, embedding_size], -1.0, 1.0),
                    name="W")
                self.embedded_chars = tf.nn.embedding_lookup(W, self.input_x)
                self.embedded_chars_expanded = tf.expand_dims(self.embedded_chars, -1)
        else:
            self.embedded_chars_expanded = tf.expand_dims(tf.expand_dims(self.input_x, -1), -1)

        # Create a convolution + maxpool layer for each filter size
        pooled_outputs = []
        for i, filter_size in enumerate(filter_sizes):
            with tf.name_scope("conv-maxpool-%s" % filter_size):
                # Convolution Layer
                filter_shape = [filter_size, embedding_size, 1, num_filters]
                W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")
                b = tf.Variable(tf.constant(0.1, shape=[num_filters]), name="b")
                conv = tf.nn.conv2d(
                    self.embedded_chars_expanded,
                    W,
                    strides=[1, 1, 1, 1],
                    padding="VALID",
                    name="conv")
                # Apply nonlinearity
                h = tf.nn.relu(tf.nn.bias_add(conv, b), name="relu")
                # Maxpooling over the outputs
                pooled = tf.nn.max_pool(
                    h,
                    ksize=[1, sequence_length - filter_size + 1, 1, 1],
                    strides=[1, 1, 1, 1],
                    padding='VALID',
                    name="pool")
                pooled_outputs.append(pooled)

        # Combine all the pooled features
        num_filters_total = num_filters * len(filter_sizes)
        self.h_pool = tf.concat(3, pooled_outputs)
        self.h_pool_flat = tf.reshape(self.h_pool, [-1, num_filters_total])

        self.pre_readout = self.h_pool_flat
        pre_readout_size = num_filters_total

        for i in xrange(hidden_layers):
            with tf.name_scope("hidden{}".format(i)):
                W = tf.Variable(tf.truncated_normal([pre_readout_size, hidden_layer_size], stddev=0.1), name="W")
                b = tf.Variable(tf.constant(0.1, shape=[hidden_layer_size]), name="b")
                l2_loss += tf.nn.l2_loss(W)
                l2_loss += tf.nn.l2_loss(b)
                self.pre_readout = tf.nn.relu_layer(tf.nn.dropout(self.pre_readout, self.dropout_keep_prob), W, b)
                pre_readout_size = hidden_layer_size # now this many outputs

        # Add dropout
        with tf.name_scope("dropout"):
            self.h_drop = tf.nn.dropout(self.pre_readout, self.dropout_keep_prob)

        # Final (unnormalized) scores and predictions
        with tf.name_scope("output"):
            W = tf.Variable(tf.truncated_normal([pre_readout_size, num_classes], stddev=0.1), name="W")
            b = tf.Variable(tf.constant(0.1, shape=[num_classes]), name="b")
            l2_loss += tf.nn.l2_loss(W)
            l2_loss += tf.nn.l2_loss(b)
            self.scores = tf.nn.xw_plus_b(self.h_drop, W, b, name="scores")
            self.predictions = tf.argmax(self.scores, 1, name="predictions")

        # Calculate mean cross-entropy loss
        with tf.name_scope("loss"):
            losses = tf.nn.softmax_cross_entropy_with_logits(self.scores, self.input_y)
            # penalize false positives more than false negatives
            if loss_asymmetry:
                # convert labels into 0,1,0,1,... weights where 1 is a NEGATIVE example
                weights = tf.squeeze(tf.slice(self.input_y, [0,0], [-1,1]))
                losses += loss_asymmetry * losses * weights
            self.loss = tf.reduce_mean(losses) + l2_reg_lambda * l2_loss

        # Accuracy
        with tf.name_scope("accuracy"):
            correct_predictions = tf.equal(self.predictions, tf.argmax(self.input_y, 1))
            self.accuracy = tf.reduce_mean(tf.cast(correct_predictions, "float"), name="accuracy")

