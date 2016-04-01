#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Python implemenation of the client's BinaryHeap.js
# SP3RDPARTY : BinaryHeap.js : CC-by License

class BinaryHeap(object):
    def __init__(self):
        self.content = []
    def push(self, element, score):
        element.heapscore = score
        self.content.append(element)
        self.sinkDown(len(self.content) - 1)
    def size(self): return len(self.content)
    def rescoreElement(self, node, newscore):
        node.heapscore = newscore
        self.sinkDown(self.content.index(node))
    def sinkDown(self, n):
        element = self.content[n]
        # When at 0, an element can not sink any further.
        while n > 0:
            # Compute the parent element's index, and fetch it.
            parentN = ((n + 1) >> 1) - 1
            parent = self.content[parentN]
            # Swap the elements if the parent is greater.
            if element.heapscore < parent.heapscore:
                self.content[parentN] = element
                self.content[n] = parent
                # Update 'n' to continue at the new position.
                n = parentN
            # Found a parent that is less, no need to sink any further.
            else:
                break
    def pop(self):
        result = self.content[0]
        # Get the element at the end of the array.
        end = self.content.pop()
        # If there are any elements left, put the end element at the
        # start, and let it bubble up.
        if len(self.content) > 0:
            self.content[0] = end
            self.bubbleUp(0)
        return result
    def bubbleUp(self, n):
        # Look up the target element and its score.
        length = len(self.content)
        element = self.content[n]
        elemScore = element.heapscore

        while True:
            # Compute the indices of the child elements.
            child2N = (n + 1) << 1
            child1N = child2N - 1
            swap = None
            # If the first child exists (is inside the array)...
            if child1N < length:
                # Look it up and compute its score.
                child1 = self.content[child1N]
                child1Score = child1.heapscore
                # If the score is less than our element's, we need to swap.
                if child1Score < elemScore:
                    swap = child1N

            # Do the same checks for the other child.
            if child2N < length:
                child2 = self.content[child2N]
                child2Score = child2.heapscore
                if child2Score < (elemScore if swap is None else child1Score):
                    swap = child2N

            # If the element needs to be moved, swap it, and continue.
            if swap is not None:
                self.content[n] = self.content[swap]
                self.content[swap] = element
                n = swap
            else:
                break

if __name__ == '__main__':
    class MyElement(object):
        def __init__(self):
            self.heapscore = 0

    heap = BinaryHeap()
    heap.push(MyElement(), 10)
    heap.push(MyElement(), 4)
    heap.push(MyElement(), 5)
    heap.push(MyElement(), 1)
    temp = MyElement()
    heap.push(temp, 30)
    heap.rescoreElement(temp, 20)
    while heap.size() > 0:
        print heap.pop().heapscore


