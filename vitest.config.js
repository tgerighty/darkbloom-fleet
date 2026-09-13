export default {
  test: {
    include: ["tests/**/*.test.js"],
    coverage: {
      provider: "v8",
      include: ["fleet/static/hourly.js"],
      all: true,
    },
  },
};
