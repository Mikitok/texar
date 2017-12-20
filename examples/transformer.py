"""
Example pipeline. This is a minimal example of basic RNN language model.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# pylint: disable=invalid-name, no-name-in-module
import random
import numpy as np
import tensorflow as tf
from texar.data import PairedTextDataBase
from texar.modules import TransformerEncoder, TransformerDecoder
from texar.losses import mle_losses
from texar.core import optimization as opt
from texar import context

if __name__ == "__main__":
    ### Build data pipeline
    tf.set_random_seed(123)
    np.random.seed(123)
    random.seed(123)
    data_hparams = {
        "num_epochs": 25,
        "seed": 123,
        "batch_size": 32,
        "shuffle": True,
        "source_dataset": {
            "files": ['data/translation/de-en/train_de_sentences.txt'],
            "vocab_file": 'data/translation/de-en/filter_de.vocab.txt',
            "processing": {
                "bos_token": "<S>",
                "eos_token": "</S>",
            }
        },
        "target_dataset": {
            "files": ['data/translation/de-en/train_en_sentences.txt'],
            "vocab_file": 'data/translation/de-en/filter_en.vocab.txt',
            "processing":{
                "bos_token": "<S>",
                "eos_token": "</S>",
            },
        }
    }
    extra_hparams = {
        'max_seq_length':10,
        'scale':True,
        'sinusoid':False,
        'embedding': {
            'name': 'lookup_table',
            'dim': 512,
            'initializer': {
                'type': tf.contrib.layers.xavier_initializer(),
            },
            'trainable':True,
        },
        'num_blocks': 6,
        'num_heads': 8,
        'poswise_feedforward': {
            'name':'multihead_attention',
            'layers':[
                {
                    'type':'Conv1D',
                    'kwargs': {
                        'filters':512*4,
                        'kernel_size':1,
                        'activation':'relu',
                        'use_bias':True,
                    }
                },
                {
                    'type':'Conv1D',
                    'kwargs': {
                        'filters':512,
                        'kernel_size':1,
                        'use_bias':True,
                    }
                }
            ],
        },
    }
    # Construct the database
    text_database = PairedTextDataBase(data_hparams)
    text_data_batch = text_database()
    ori_src_text = text_data_batch['source_text_ids']
    ori_tgt_text = text_data_batch['target_text_ids']

    padded_src_text = tf.concat([ori_src_text, tf.zeros([tf.shape(ori_src_text)[0],\
        extra_hparams['max_seq_length']+1-tf.shape(ori_src_text)[1]], dtype=tf.int64)], axis=1)
    padded_tgt_text = tf.concat([ori_tgt_text, tf.zeros([tf.shape(ori_tgt_text)[0],\
        extra_hparams['max_seq_length']+1-tf.shape(ori_tgt_text)[1]], dtype=tf.int64)], axis=1)
    encoder_input = padded_src_text[:, 1:]
    decoder_input = padded_tgt_text[:, :-1]
    encoder = TransformerEncoder(vocab_size=text_database.source_vocab.vocab_size,\
        hparams=extra_hparams)
    encoder_output = encoder(encoder_input)

    decoder = TransformerDecoder(vocab_size=text_database.target_vocab.vocab_size,\
            hparams=extra_hparams)
    logits, preds = decoder(decoder_input, encoder_output)
    loss_params = {
        'label_smoothing':0.1,
    }

    labels = padded_tgt_text[:, 1:]

    smooth_labels = mle_losses.label_smoothing(labels, text_database.target_vocab.vocab_size, \
        loss_params['label_smoothing'])
    mle_loss = mle_losses.average_sequence_softmax_cross_entropy(
        labels=smooth_labels,
        logits=logits,
        sequence_length=text_data_batch['target_length']-1)

    opt_hparams = {
        "optimizer": {
            "type": "AdamOptimizer",
            "kwargs": {
                "learning_rate": 0.0001,
                "beta1": 0.9,
                "beta2": 0.98,
                "epsilon": 1e-8,
            }
        }
    }

    train_op, global_step = opt.get_train_op(mle_loss, hparams=opt_hparams)
    merged = tf.summary.merge_all()
    saver = tf.train.Saver(max_to_keep=10)

    with tf.Session() as sess:

        sess.run(tf.global_variables_initializer())
        sess.run(tf.local_variables_initializer())
        sess.run(tf.tables_initializer())
        writer = tf.summary.FileWriter("./logdir/", graph=sess.graph)
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)

        try:
            while not coord.should_stop():
                source, target, predict, _, step, loss, mgd = sess.run(
                    [encoder_input, labels, preds, train_op, global_step, mle_loss, merged],
                    feed_dict={context.is_train(): True})
                writer.add_summary(mgd, global_step=step)
                if step % 1703 == 0:
                    print('step:{} loss:{}'.format(step, loss))
                    saver.save(sess, './logdir/my-model', global_step=step)
        except tf.errors.OutOfRangeError:
            print('Done -- epoch limit reached')
        finally:
            coord.request_stop()
        coord.join(threads)
        saver.save(sess, './logdir/my-model', global_step=step)