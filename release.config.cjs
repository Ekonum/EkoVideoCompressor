module.exports = {
  branches: ["main"],
  tagFormat: "v${version}",
  plugins: [
    [
      "@semantic-release/commit-analyzer",
      {
        // La webapp transcript.ekonum.fr vit dans le même dépôt mais se
        // déploie seule (image `latest`, deploy-web.yml) : ses commits ne
        // doivent pas publier une version de l'app macOS qui n'a pas
        // changé. Le moteur partagé (odoo, transcription) garde ses règles.
        releaseRules: [{ scope: "web", release: false }]
      }
    ],
    "@semantic-release/release-notes-generator",
    [
      "@semantic-release/exec",
      {
        prepareCmd: "scripts/build_macos.sh ${nextRelease.version}"
      }
    ],
    [
      "@semantic-release/github",
      {
        assets: [
          {
            path: "dist/release/*.zip",
            label: "EkoVideo Compressor macOS Apple Silicon"
          }
        ],
        successComment: false,
        failComment: false
      }
    ]
  ]
};
