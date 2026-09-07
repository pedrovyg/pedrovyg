export default {
  multipass: false,
  js2svg: {
    pretty: false,
    indent: 0,
  },
  plugins: [
    "removeXMLProcInst",
    {
      name: "removeComments",
      params: {
        preservePatterns: [],
      },
    },
    "removeMetadata",
    "removeEditorsNSData",
    "sortAttrs",
  ],
};

// Deliberately excluded: preset-default, cleanupIds, minifyStyles,
// inlineStyles, convertStyleToAttrs, removeHiddenElems, removeUnknownsAndDefaults,
// convertPathData, mergePaths, and every transformation that can rewrite text,
// CSS, animation classes, referenced IDs, or preformatted ASCII whitespace.
