goog.provide('BinaryHeap');

// from http://eloquentjavascript.net/1st_edition/appendix2.html
// via https://github.com/bgrins/javascript-astar
// License: http://creativecommons.org/licenses/by/3.0/

// SP3RDPARTY : BinaryHeap.js : CC-by License

/** @interface */
BinaryHeap.Element = function() {};
/** @type {number}
    Inline .heapscore property. This is stored inside the object because it is critical to performance. */
BinaryHeap.Element.prototype.heapscore;

/** @constructor @struct */
BinaryHeap.BinaryHeap = function() {
    /** @type {!Array.<!BinaryHeap.Element>} */
    this.content = [];
};

/** @param {!BinaryHeap.Element} element
    @param {number} score */
BinaryHeap.BinaryHeap.prototype.push = function(element, score) {
    // Add the new element to the end of the array.
    element.heapscore = score;
    this.content.push(element);
    // Allow it to sink down.
    this.sinkDown(this.content.length - 1);
};

/** return first element, but do not remove it from the heap
    @return {!BinaryHeap.Element} */
BinaryHeap.BinaryHeap.prototype.peek = function() { return this.content[0]; };

/** @return {!BinaryHeap.Element} */
BinaryHeap.BinaryHeap.prototype.pop = function() {
    // Store the first element so we can return it later.
    var result = this.content[0];
    // Get the element at the end of the array.
    var end = this.content.pop();
    // If there are any elements left, put the end element at the
    // start, and let it bubble up.
    if (this.content.length > 0) {
      this.content[0] = end;
      this.bubbleUp(0);
    }
    return result;
};

/** @param {!BinaryHeap.Element} node */
BinaryHeap.BinaryHeap.prototype.remove = function(node) {
    var i = this.content.indexOf(node);

    // When it is found, the process seen in 'pop' is repeated
    // to fill up the hole.
    var end = this.content.pop();
    if (i != this.content.length - 1) {
      this.content[i] = end;
      if (end.heapscore < node.heapscore)
        this.sinkDown(i);
      else
        this.bubbleUp(i);
    }
};

/** @return {number} */
BinaryHeap.BinaryHeap.prototype.size = function() {
    return this.content.length;
};

/** @param {!BinaryHeap.Element} node
    @param {number} newscore */
BinaryHeap.BinaryHeap.prototype.rescoreElement = function(node, newscore) {
      node.heapscore = newscore;
      for(var n = 0; n < this.content.length; n++) {
          if(this.content[n] === node) {
              break;
          }
      }
      if(n == this.content.length) {
          console.log("rescoreElement on invalid node!");
      } else {
          this.sinkDown(n);
      }
};

/** @param {number} n */
BinaryHeap.BinaryHeap.prototype.sinkDown = function(n) {
    // Fetch the element that has to be sunk.
    var element = this.content[n];
    // When at 0, an element can not sink any further.
    while (n > 0) {
      // Compute the parent element's index, and fetch it.
      var parentN = ((n + 1) >> 1) - 1,
          parent = this.content[parentN];
      // Swap the elements if the parent is greater.
      if (element.heapscore < parent.heapscore) {
        this.content[parentN] = element;
        this.content[n] = parent;
        // Update 'n' to continue at the new position.
        n = parentN;
      }
      // Found a parent that is less, no need to sink any further.
      else {
        break;
      }
    }
};

/** @param {number} n */
BinaryHeap.BinaryHeap.prototype.bubbleUp = function(n) {
    // Look up the target element and its score.
    var length = this.content.length,
        element = this.content[n],
        elemScore = element.heapscore;

    while(true) {
      // Compute the indices of the child elements.
      var child2N = (n + 1) << 1, child1N = child2N - 1;
      // This is used to store the new position of the element,
      // if any.
      var swap = null;
      // If the first child exists (is inside the array)...
      if (child1N < length) {
        // Look it up and compute its score.
        var child1 = this.content[child1N],
            child1Score = child1.heapscore;
        // If the score is less than our element's, we need to swap.
        if (child1Score < elemScore)
          swap = child1N;
      }
      // Do the same checks for the other child.
      if (child2N < length) {
        var child2 = this.content[child2N],
            child2Score = child2.heapscore;
        if (child2Score < (swap == null ? elemScore : child1Score))
          swap = child2N;
      }

      // If the element needs to be moved, swap it, and continue.
      if (swap != null) {
        this.content[n] = this.content[swap];
        this.content[swap] = element;
        n = swap;
      }
      // Otherwise, we are done.
      else {
        break;
      }
    }
};

/*
  test code:
        var heap = new BinaryHeap.BinaryHeap(function(x){return x.val;});
        var vals = [10, 3, 4, 8, 2, 2.5, 9, 7, 1, 2, 6, 5];
        var a = [];
        for(var i = 0; i < vals.length; i++) {
            a.push({val:vals[i]});
            heap.push(a[i]);
        }
        a[1].val = 3.333;
        heap.rescoreElement(a[0]);
        while (heap.size() > 0)
            console.log(heap.pop().val);
*/
