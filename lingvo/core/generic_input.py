# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Generic input."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import lingvo.compat as tf
from lingvo.core import ops
from lingvo.core import py_utils
from tensorflow.python.framework import function  # pylint:disable=g-direct-tensorflow-import


# TODO(zhifengc): Changes processor's requirement to return a
# tuple of (output, bucket_key) to be consistent w/ the return
# value of GenericInput().
def GenericInput(processor, *args, **kwargs):
  """Builds a generic input pipeline.

  Example usage::

    def ParseRecord(record):
      # Given a tf.string record, return a (NestedMap, bucketing key) pair.
      feature_map = ...
      features = tf.parse_single_example(record, feature_map)
      # Each example is represented by a NestedMap of tensors (without a
      # batch dimension).
      example = py_utils.NestedMap(field1=..., field2=...)
      # bucketing_key is a scalar convertible to tf.int32.
      # Use 1 if all examples are of the same size.
      bucketing_key = 1
      return example, bucketing_key

    input_batch, bucket_keys = GenericInput(ParseRecord, file_pattern=..., ...)
    # input_batch is a NestedMap of tensors, where dim 0 of each tensor
    # represents the batch dimension.
    input_batch.field1 = ...

  Args:
    processor: a function that takes a string record as input and returns a
      tuple (output, bucketing_key). `output` must be a NestedMap or a list of
      tensors representing one example. The `bucketing_key` must be a scalar
      convertible to a tf.int32 tensor that represents the bucketing key (e.g.,
      sequence length for sequence inputs). If `bucketing_key` is a negative
      number, the record is dropped.
    *args: additional args for x_ops.generic_input.
    **kwargs: additional keyword args for x_ops.generic_input.

  Returns:
    A tuple of (outputs, bucket_keys):

    - outputs: a NestedMap or a list of tensors, similar to `processor`'s
      return,  except every tensor will have an additional dimension 0 that
      represents the batch dimension.
    - bucket_keys: a tf.int32 vector.
  """
  output_tmpl = py_utils.NestedMap()

  def _FlatOutputProcessor(inputs):
    """Returns a flattened list of 'processor(inputs)'."""
    output, bucketing_key = processor(inputs)
    if isinstance(output, list):
      assert output
      assert all(isinstance(x, tf.Tensor) for x in output), '{}'.format(output)
    else:
      assert isinstance(output, py_utils.NestedMap), '{}'.format(output)
      assert output
      assert all(
          isinstance(x, tf.Tensor) for x in output.Flatten()), '{}'.format(
              output.DebugString())
    bucketing_key = tf.to_int32(bucketing_key)
    tf.logging.debug('Processor outputs=%s bucketing_key=%s', output,
                     bucketing_key)
    output_tmpl.out_values = output
    flat_output_tmpl = output_tmpl.Flatten()
    tf.logging.debug('Processor flat outputs=%s', flat_output_tmpl)
    tf.logging.debug('extra_inputs=%s extra_args=%s extra_vars=%s',
                     function.get_extra_inputs(), function.get_extra_args(),
                     function.get_extra_vars())
    assert not function.get_extra_args(), (
        'fns {} is not pure: extra_args={}'.format(processor,
                                                   function.get_extra_args()))
    return flat_output_tmpl + [bucketing_key]

  proc_fn = tf.Defun(tf.string)(_FlatOutputProcessor)

  out_types = [
      tf.DType(a.type) for a in proc_fn.definition.signature.output_arg
  ]
  assert out_types[-1] == tf.int32, ('%s is not expected.' % out_types[-1])
  flat_outputs, bucket_keys = ops.gen_x_ops.generic_input(
      processor=proc_fn, out_types=out_types[:-1], *args, **kwargs)
  tf.logging.debug('x_ops.generic_input flat_outputs=%s', flat_outputs)
  # Pack flat_outputs to outputs.
  outputs = output_tmpl.Pack(flat_outputs).out_values
  tf.logging.debug('x_ops.generic_input outputs=%s', outputs)
  return outputs, bucket_keys
