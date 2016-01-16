import numpy as np
import re
import os
import sys
import itertools
from collections import Counter

def get_chat_filter(enabled):
    if enabled:
        import ChatFilter, SpinConfig
        return ChatFilter.ChatFilter(SpinConfig.load(SpinConfig.gamedata_component_filename('chat_filter.json')))
    else:
        return None

def clean_str(string, cf):
    """
    Tokenization/string cleaning
    """
    string = string.lower()

    # leet-speak replacements
    if cf:
        for original, alts in cf.leet_speak.iteritems():
            if len(original) == 1:
                string = re.sub(r"["+alts+r"]", original, string)

    string = re.sub(r"[^A-Za-z]", "", string)
    #string = re.sub(r",", " , ", string)
    #string = re.sub(r"!", " ! ", string)
    #string = re.sub(r"\(", " \( ", string)
    #string = re.sub(r"\)", " \) ", string)
    #string = re.sub(r"\?", " \? ", string)
    #string = re.sub(r"\s{2,}", " ", string)
    return string.strip()


def load_data_and_labels(data_dir, mode, use_chat_filter):
    """
    Loads MR polarity data from files, splits the data into words and generates labels.
    Returns split sentences and labels.
    """
    cf = get_chat_filter(use_chat_filter)

    # Load data from files
    positive_examples = []
    negative_examples = []

    for line in open(os.path.join(data_dir, "game-bad.txt")).readlines():
        line = line.decode('utf-8').strip()
        line = clean_str(line, cf)
        if len(line) < 3: continue # string too short
        positive_examples.append(line)

    for line in open(os.path.join(data_dir, "game-good.txt")).readlines():
        line = line.decode('utf-8').strip()
        dest = negative_examples
        if cf and cf.is_bad(line):
            # swap to positive
            dest = positive_examples
        line = clean_str(line, cf)
        if len(line) < 3: continue # string too short
        dest.append(line)

    if abs(len(positive_examples)-len(negative_examples)) >= 0.5*(len(positive_examples)+len(negative_examples)):
        print("equalizing lengths..")
        smaller, larger = (positive_examples, negative_examples) if len(positive_examples) < len(negative_examples) else (negative_examples, positive_examples)
        copies = len(larger) // len(smaller)
        smaller *= copies
        print("new lengths: {} {}".format(len(positive_examples),len(negative_examples)))

    # Split by words
    x_text = positive_examples + negative_examples
    x_text = split_input(x_text, mode)

    # Generate labels
    positive_labels = [[0, 1] for _ in positive_examples]
    negative_labels = [[1, 0] for _ in negative_examples]
    y = np.concatenate([positive_labels, negative_labels], 0)
    return [x_text, y]

def split_input(input, mode):
    """
    Split array of sentences into array of arrays of words or characters
    """
    if mode == 'characters':
        return [[c for c in s if c != ' '] for s in input]
    elif mode == 'words':
        return [s.split(" ") for s in input]

def load_infer_source(mode, use_chat_filter, name):
    cf = get_chat_filter(use_chat_filter)

    examples = []
    labels = []
    fd = sys.stdin if name == "-" else open(name)
    for line in fd.readlines():
        examples.append(clean_str(line.decode('utf-8').strip(), cf))
        labels.append([1, 0]) # negative
    examples = split_input(examples, mode)
    return [examples, labels]

def pad_sentences(sentences, saved_sequence_length=None, padding_word="<PAD/>"):
    """
    Pads all sentences to the same length. The length is defined by the longest sentence.
    Returns padded sentences.
    """
    if saved_sequence_length:
        sequence_length = saved_sequence_length
    else:
        sequence_length = max(len(x) for x in sentences)
    padded_sentences = []
    for i in range(len(sentences)):
        sentence = sentences[i]
        num_padding = sequence_length - len(sentence)
        if num_padding < 0:
            new_sentence = sentence[:num_padding] # chop off the end
        else:
            new_sentence = sentence + [padding_word] * num_padding
        padded_sentences.append(new_sentence)
    return padded_sentences


def build_vocab(sentences, saved_vocabulary_inv):
    """
    Builds a vocabulary mapping from word to index based on the sentences.
    Returns vocabulary mapping and inverse vocabulary mapping.
    Optionally, re-use a saved vocabulary
    """
    if saved_vocabulary_inv:
        vocabulary_inv = saved_vocabulary_inv
    else:
        # Build vocabulary
        word_counts = Counter(itertools.chain(*sentences))
        # Mapping from index to word
        vocabulary_inv = [x[0] for x in word_counts.most_common()]
    # Mapping from word to index
    vocabulary = {x: i for i, x in enumerate(vocabulary_inv)}
    return [vocabulary, vocabulary_inv]


def build_input_data(sentences, labels, vocabulary):
    """
    Maps sentencs and labels to vectors based on a vocabulary.
    """
    x = np.array([[vocabulary[word] for word in sentence] for sentence in sentences])
    y = np.array(labels)
    return [x, y]


def load_data(data_dir, mode, use_chat_filter, saved_vocabulary_inv, saved_sequence_length, infer_source):
    """
    Loads and preprocessed data for the MR dataset.
    Returns input vectors, labels, vocabulary, and inverse vocabulary.
    """
    # Load and preprocess data
    if infer_source:
        sentences, labels = load_infer_source(mode, use_chat_filter, infer_source)
    else:
        sentences, labels = load_data_and_labels(data_dir, mode, use_chat_filter)
    sentences_padded = pad_sentences(sentences, saved_sequence_length)
    vocabulary, vocabulary_inv = build_vocab(sentences_padded, saved_vocabulary_inv)
    x, y = build_input_data(sentences_padded, labels, vocabulary)
    return [x, y, vocabulary, vocabulary_inv]


def batch_iter(data, batch_size, num_epochs):
    """
    Generates a batch iterator for a dataset.
    """
    data = np.array(data)
    data_size = len(data)
    num_batches_per_epoch = int(len(data)/batch_size) + 1
    for epoch in range(num_epochs):
        # Shuffle the data at each epoch
        shuffle_indices = np.random.permutation(np.arange(data_size))
        shuffled_data = data[shuffle_indices]
        for batch_num in range(num_batches_per_epoch):
            start_index = batch_num * batch_size
            end_index = min((batch_num + 1) * batch_size, data_size)
            yield epoch, batch_num, shuffled_data[start_index:end_index]
