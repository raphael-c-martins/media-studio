import instaloader

def test_nodes(shortcode):
    L = instaloader.Instaloader(quiet=True)
    post = instaloader.Post.from_shortcode(L.context, shortcode)
    print("Mediacount:", post.mediacount)
    try:
        nodes = list(post.get_sidecar_nodes())
        print("Nodes count:", len(nodes))
        for idx, n in enumerate(nodes):
            print(f"Node {idx+1}: is_video={n.is_video}, display_url={n.display_url[:60]}")
    except Exception as e:
        print("Erro em get_sidecar_nodes:", e)

if __name__ == "__main__":
    test_nodes("Dcrhp_1lh2D")
