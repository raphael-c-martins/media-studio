import instaloader

def inspect_post(shortcode):
    L = instaloader.Instaloader(quiet=True)
    post = instaloader.Post.from_shortcode(L.context, shortcode)
    print(f"Título/Autor: {post.owner_username} | Título: {(post.caption or '')[:40]}")
    print(f"É vídeo? {post.is_video} | Mediacount: {post.mediacount}")
    
    if post.mediacount > 1:
        for i, node in enumerate(post.get_sidecar_nodes()):
            url = node.video_url if node.is_video else node.display_url
            print(f" -> Item {i+1}: is_video={node.is_video} | URL={url[:60]}...")
    else:
        url = post.video_url if post.is_video else post.url
        print(f" -> Item único: URL={url[:60]}...")

if __name__ == "__main__":
    inspect_post("Dcrhp_1lh2D")
