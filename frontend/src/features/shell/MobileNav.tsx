import { Menu } from "lucide-react";
import { useState } from "react";

import { Drawer } from "@/ui/Drawer";
import { IconButton } from "@/ui/IconButton";
import { Sidebar } from "./Sidebar";

export function MobileNav() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <IconButton
        aria-label="Open navigation"
        icon={<Menu size={18} />}
        className="lg:hidden"
        onClick={() => setOpen(true)}
      />
      <Drawer open={open} onOpenChange={setOpen} title="Navigate" side="left">
        <Sidebar onNavigate={() => setOpen(false)} className="-mx-5 -my-4 px-2 py-0" />
      </Drawer>
    </>
  );
}
