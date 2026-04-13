import { motion } from 'framer-motion';

export const Greeting = () => {
  return (
    <div
      key="overview"
      className="mx-auto mt-4 flex size-full max-w-3xl flex-col items-center justify-center px-4 md:mt-16 md:px-8"
    >
      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, scale: 0.7 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.7 }}
        transition={{ delay: 0.2, type: 'spring', stiffness: 200, damping: 15 }}
        className="mb-6"
      >
        <img
          src="https://i.postimg.cc/h4dnNdHq/Vector-style-C3OD-lo.png"
          alt="dbx-unifiedchat logo"
          className="h-64 w-auto drop-shadow-lg"
        />
      </motion.div>

      {/* Colorful gradient headline */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.5 }}
        className="font-bold text-2xl md:text-3xl bg-gradient-to-r from-green-500 via-blue-500 to-blue-500 bg-clip-text text-transparent"
      >
        Chat with your Data
      </motion.div>

      {/* Colorful tag pills */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.75 }}
        className="mt-6 flex flex-wrap justify-center gap-2"
      >
      </motion.div>
    </div>
  );
};
